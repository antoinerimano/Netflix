# reco/lists.py
"""
Lists a profile makes ("Best heist movies"), private until shared at /l/<share_id>.

Owner (signed in, its own profile):
  GET    /api/lists/?profileId=..[&titleId=..]   -> {"lists": [summary (+ "contains")], "max": 50}
  POST   /api/lists/?profileId=..  {name, description?, title_id?}  -> summary (created, with the title)
  GET    /api/lists/<id>/?profileId=..           -> summary + {"items": [{"title": {...}, "added_at"}]}
  PATCH  /api/lists/<id>/?profileId=..  {name?, description?, is_public?}  -> summary
  DELETE /api/lists/<id>/?profileId=..
  PUT    /api/lists/<id>/items/<title_id>/?profileId=..   add a title
  DELETE /api/lists/<id>/items/<title_id>/?profileId=..   remove it
Anyone, once shared:
  GET    /api/public-lists/<share_id>/           -> {name, description, owner, items, count, updated_at}
  POST   /api/public-lists/<share_id>/copy/?profileId=..  -> a private copy in the viewer's lists
summary = {id, name, description, count, is_public, share_id, covers: [up to 4 posters], updated_at}

The owner sees its lists through its age limit; a shared list shows everything in it (it's the
owner's choice, like a link to the titles' public pages). The owner's profile name is shown as
the author of a shared list (the page says so before sharing).
"""
import secrets
import string

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from users.maturity import allowed_titles_q
from users.models import Profile, Title

from .models import UserList, UserListItem

MAX_LISTS = 50
MAX_ITEMS = 500
NAME_MAX = 80
DESCRIPTION_MAX = 300
SHARE_ALPHABET = string.ascii_lowercase + string.digits
ITEM_FIELDS = ("id", "type", "title", "poster", "landscape_image", "release_year", "rating", "description")


def _new_share_id():
    return "".join(secrets.choice(SHARE_ALPHABET) for _ in range(10))


def _card(t):
    return {f: getattr(t, f) for f in ITEM_FIELDS}


def _summary(lst, covers=None, count=None):
    return {
        "id": lst.id,
        "name": lst.name,
        "description": lst.description,
        "count": count if count is not None else lst.items.count(),
        "is_public": lst.is_public,
        "share_id": lst.share_id,
        "covers": covers if covers is not None else [],
        "updated_at": lst.updated_at.isoformat(),
    }


def _clean(request, partial=False):
    """(fields, error) from the request body."""
    out = {}
    if "name" in request.data or not partial:
        name = " ".join(str(request.data.get("name") or "").split())
        if not name:
            return None, "Give the list a name."
        out["name"] = name[:NAME_MAX]
    if "description" in request.data:
        out["description"] = str(request.data.get("description") or "").strip()[:DESCRIPTION_MAX]
    if partial and "is_public" in request.data:
        out["is_public"] = bool(request.data.get("is_public"))
    return out, None


def _profile(request):
    return get_object_or_404(Profile, id=request.query_params.get("profileId"), user=request.user)


def _own_list(request, list_id):
    profile = _profile(request)
    return profile, get_object_or_404(UserList, id=list_id, profile=profile)


def _list_items(lst, profile=None):
    qs = UserListItem.objects.filter(user_list=lst).select_related("title").order_by("added_at", "id")
    if profile is not None:
        qs = qs.filter(allowed_titles_q(profile, prefix="title__"))
    return [{"title": _card(i.title), "added_at": i.added_at.isoformat()} for i in qs]


class ListsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _profile(request)
        lists = list(UserList.objects.filter(profile=profile).order_by("-updated_at", "-id"))
        allowed = allowed_titles_q(profile, prefix="title__")
        covers, counts = {}, {}
        for item in (
            UserListItem.objects.filter(user_list__in=lists).filter(allowed)
            .select_related("title").only("user_list_id", "title__poster").order_by("-added_at")
        ):
            counts[item.user_list_id] = counts.get(item.user_list_id, 0) + 1
            if item.title.poster and len(covers.setdefault(item.user_list_id, [])) < 4:
                covers[item.user_list_id].append(item.title.poster)
        title_id = request.query_params.get("titleId")
        containing = set()
        if title_id and str(title_id).isdigit():
            containing = set(UserListItem.objects.filter(user_list__in=lists, title_id=int(title_id))
                             .values_list("user_list_id", flat=True))
        out = []
        for lst in lists:
            s = _summary(lst, covers.get(lst.id, []), counts.get(lst.id, 0))
            if title_id:
                s["contains"] = lst.id in containing
            out.append(s)
        return Response({"lists": out, "max": MAX_LISTS})

    def post(self, request):
        profile = _profile(request)
        if UserList.objects.filter(profile=profile).count() >= MAX_LISTS:
            return Response({"code": "too_many", "detail": f"{MAX_LISTS} lists at most."}, status=400)
        fields, error = _clean(request)
        if error:
            return Response({"code": "name_required", "detail": error}, status=400)
        title_id = request.data.get("title_id")
        title = get_object_or_404(Title.objects.only("id"), id=title_id) if title_id else None
        for _ in range(5):  # a share id already taken (very unlikely): draw again
            try:
                with transaction.atomic():
                    lst = UserList.objects.create(profile=profile, share_id=_new_share_id(), **fields)
                break
            except IntegrityError:
                continue
        if title:
            UserListItem.objects.create(user_list=lst, title=title)
        return Response(_summary(lst, [title.poster] if title and getattr(title, "poster", "") else []), status=201)


class ListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, list_id):
        profile, lst = _own_list(request, list_id)
        items = _list_items(lst, profile)
        return Response({
            **_summary(lst, [i["title"]["poster"] for i in items if i["title"]["poster"]][:4], len(items)),
            "items": items,
        })

    def patch(self, request, list_id):
        _, lst = _own_list(request, list_id)
        fields, error = _clean(request, partial=True)
        if error:
            return Response({"code": "name_required", "detail": error}, status=400)
        for k, v in fields.items():
            setattr(lst, k, v)
        lst.save()
        return Response(_summary(lst))

    def delete(self, request, list_id):
        _, lst = _own_list(request, list_id)
        lst.delete()
        return Response(status=204)


class ListItemView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request, list_id, title_id):
        _, lst = _own_list(request, list_id)
        title = get_object_or_404(Title.objects.only("id"), id=title_id)
        if lst.items.count() >= MAX_ITEMS:
            return Response({"code": "too_many", "detail": f"{MAX_ITEMS} titles per list at most."}, status=400)
        UserListItem.objects.get_or_create(user_list=lst, title=title)
        lst.save(update_fields=["updated_at"])
        return Response({"ok": True})

    def delete(self, request, list_id, title_id):
        _, lst = _own_list(request, list_id)
        UserListItem.objects.filter(user_list=lst, title_id=title_id).delete()
        lst.save(update_fields=["updated_at"])
        return Response({"ok": True})


def _public(share_id):
    return get_object_or_404(UserList.objects.select_related("profile"), share_id=share_id, is_public=True)


class PublicListView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []  # no session needed: anyone with the link

    def get(self, request, share_id):
        lst = _public(share_id)
        items = _list_items(lst)
        return Response({
            "name": lst.name,
            "description": lst.description,
            "owner": lst.profile.name,
            "count": len(items),
            "items": items,
            "updated_at": lst.updated_at.isoformat(),
        })


class PublicListCopyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, share_id):
        profile = _profile(request)
        source = _public(share_id)
        if UserList.objects.filter(profile=profile).count() >= MAX_LISTS:
            return Response({"code": "too_many", "detail": f"{MAX_LISTS} lists at most."}, status=400)
        copy = UserList.objects.create(profile=profile, name=source.name, description=source.description,
                                       share_id=_new_share_id())
        UserListItem.objects.bulk_create([
            UserListItem(user_list=copy, title_id=tid)
            for tid in source.items.order_by("added_at", "id").values_list("title_id", flat=True)
        ])
        return Response(_summary(copy), status=201)
