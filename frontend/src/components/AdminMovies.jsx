// src/components/AdminMovies.js
import React, { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { BrandLoader } from '../design';
import { makeTitlesApi } from "../api/titlesApi";
import styles from "./AdminPanel.module.css";

const initialForm = {
  // shared
  title: "",
  poster: "",
  landscape_image: "",
  description: "",
  rating: "",
  genre: "",
  cast: [],
  trailer_clip_url: "",
  // stream links are built from these ids (see Providers in the Django admin)
  tmdb_id: "",
  imdb_code: "",
  // movie-only
  director: "",
  runtime_minutes: "",
  release_date: "",
  // tv-only
  first_air_date: "",
};

function isValidUrl(url) {
  if (!url) return true;
  try {
    new URL(url);
    return true;
  } catch {
    return false;
  }
}

function isValidYyyyOrIso(s) {
  return /^(\d{4}|\d{4}-\d{2}-\d{2})$/.test(String(s || "").trim());
}

export default function AdminMovies() {
  const { t } = useTranslation("admin");
  const [mode, setMode] = useState("movie"); // 'movie' | 'tv'
  const api = useMemo(() => makeTitlesApi(mode), [mode]);

  const [rows, setRows] = useState([]);
  const [form, setForm] = useState(initialForm);
  const [editingId, setEditingId] = useState(null);
  const [errors, setErrors] = useState({});
  const [loading, setLoading] = useState(false);

  // ---- validation (mode-aware) ----
  const validate = (data) => {
    const e = {};
    if (!data.title || data.title.trim().length < 2) e.title = t("titles.errors.title");
    if (!data.genre || data.genre.trim().length < 2) e.genre = t("titles.errors.genre");
    if (!data.rating || isNaN(Number(data.rating))) e.rating = t("titles.errors.rating");
    if (!data.cast || !Array.isArray(data.cast) || !data.cast.length || !data.cast[0]) {
      e.cast = t("titles.errors.cast");
    }
    if (!/^\d+$/.test(String(data.tmdb_id || "").trim())) {
      e.tmdb_id = t("titles.errors.tmdbId");
    }
    if (data.imdb_code && !/^tt\d+$/.test(String(data.imdb_code).trim())) {
      e.imdb_code = t("titles.errors.imdbId");
    }

    // Movie-only validation
    if (mode === "movie") {
      if (!data.director || data.director.trim().length < 2) e.director = t("titles.errors.director");
      if (data.runtime_minutes && isNaN(Number(data.runtime_minutes))) {
        e.runtime_minutes = t("titles.errors.runtime");
      }
      if (!data.release_date || !isValidYyyyOrIso(data.release_date)) {
        e.release_date = t("titles.errors.date");
      }
    }

    // TV-only validation
    if (mode === "tv") {
      if (!data.first_air_date || !isValidYyyyOrIso(data.first_air_date)) {
        e.first_air_date = t("titles.errors.date");
      }
    }

    // URL checks (validate when present)
    if (!isValidUrl(data.poster)) e.poster = t("titles.errors.poster");
    if (!isValidUrl(data.landscape_image)) e.landscape_image = t("titles.errors.landscape");
    if (!isValidUrl(data.trailer_clip_url)) e.trailer_clip_url = t("titles.errors.trailer");

    return e;
  };

  // ---- load list when mode changes ----
  useEffect(() => {
    setLoading(true);
    setEditingId(null);
    setForm(initialForm);
    api.fetchAll().then(setRows).finally(() => setLoading(false));
  }, [api]);

  // ---- revalidate on form or mode change ----
  useEffect(() => {
    setErrors(validate(form));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form, mode]);

  const onChange = (e) => {
    const { name, value } = e.target;
    if (name === "cast") {
      setForm((prev) => ({
        ...prev,
        cast: value.split(",").map((s) => s.trim()).filter(Boolean),
      }));
    } else {
      setForm((prev) => ({ ...prev, [name]: value }));
    }
  };

  const onEdit = async (id) => {
    const data = await api.fetchById(id);
    setForm({
      ...initialForm,
      ...data,
      cast: Array.isArray(data.cast)
        ? data.cast
        : String(data.cast || "").split(",").map((s) => s.trim()).filter(Boolean),
      release_date: data.release_date || "",
      first_air_date: data.first_air_date || "",
      director: data.director || "",
      runtime_minutes: data.runtime_minutes || "",
      trailer_clip_url: data.trailer_clip_url || "",
      tmdb_id: data.tmdb_id ?? "",
      imdb_code: data.imdb_code || "",
    });
    setEditingId(id);
  };

  const onDelete = async (id) => {
    if (!window.confirm(t(`titles.confirmDelete_${mode}`))) return;
    await api.remove(id);
    setRows((prev) => prev.filter((r) => r.id !== id));
    if (editingId === id) {
      setEditingId(null);
      setForm(initialForm);
    }
  };

  const onSubmit = async (e) => {
    e.preventDefault();
    const v = validate(form);
    setErrors(v);
    if (Object.keys(v).length) return;

    let submit = {
      ...form,
      tmdb_id: Number(String(form.tmdb_id).trim()),
      imdb_code: String(form.imdb_code || "").trim() || null, // unique column: never send ""
    };

    if (mode === "movie") {
      delete submit.first_air_date;
    } else {
      delete submit.release_date;
      delete submit.director;
      delete submit.runtime_minutes;
    }

    setLoading(true);
    try {
      if (editingId) {
        const updated = await api.update(editingId, submit);
        setRows((prev) => prev.map((r) => (r.id === editingId ? updated : r)));
      } else {
        const created = await api.create(submit);
        setRows((prev) => [...prev, created]);
      }
      setForm(initialForm);
      setEditingId(null);
    } finally {
      setLoading(false);
    }
  };

  const castString = Array.isArray(form.cast) ? form.cast.join(", ") : "";

  const yearForRow = (r) => {
    const raw = mode === "movie"
      ? (r.release_year || r.release_date || "")
      : (r.first_air_date || r.release_date || "");
    const m = String(raw).match(/^\d{4}/)?.[0];
    return m || "";
  };

  return (
    <div className={styles["admin-panel"]}>
      <div className={styles["button-row"]} style={{ justifyContent: "space-between" }}>
        <h2>{t("titles.heading")}</h2>
        <div>
          <button
            type="button"
            className={mode === "movie" ? styles["edit-btn"] : styles["reset-btn"]}
            onClick={() => setMode("movie")}
          >
            {t("common:nav.movies")}
          </button>
          <button
            type="button"
            style={{ marginLeft: 8 }}
            className={mode === "tv" ? styles["edit-btn"] : styles["reset-btn"]}
            onClick={() => setMode("tv")}
          >
            {t("common:nav.tv")}
          </button>
        </div>
      </div>

      <form onSubmit={onSubmit} className={styles["admin-form"]}>
        <div className={styles["form-group"]}>
          <input name="title" placeholder={t("fields.title")} value={form.title} onChange={onChange} />
          {errors.title && <span className={styles.error}>{errors.title}</span>}
        </div>

        {mode === "movie" ? (
          <div className={styles["form-group"]}>
            <input
              name="release_date"
              placeholder={t("fields.releaseDate")}
              value={form.release_date}
              onChange={onChange}
            />
            {errors.release_date && <span className={styles.error}>{errors.release_date}</span>}
          </div>
        ) : (
          <div className={styles["form-group"]}>
            <input
              name="first_air_date"
              placeholder={t("fields.firstAirDate")}
              value={form.first_air_date}
              onChange={onChange}
            />
            {errors.first_air_date && <span className={styles.error}>{errors.first_air_date}</span>}
          </div>
        )}

        <div className={styles["form-group"]}>
          <input name="genre" placeholder={t("fields.genre")} value={form.genre} onChange={onChange} />
          {errors.genre && <span className={styles.error}>{errors.genre}</span>}
        </div>

        {/* Movie-only fields */}
        {mode === "movie" && (
          <>
            <div className={styles["form-group"]}>
              <input
                name="director"
                placeholder={t("fields.director")}
                value={form.director}
                onChange={onChange}
              />
              {errors.director && <span className={styles.error}>{errors.director}</span>}
            </div>

            <div className={styles["form-group"]}>
              <input
                name="runtime_minutes"
                placeholder={t("fields.runtime")}
                value={form.runtime_minutes}
                onChange={onChange}
              />
              {errors.runtime_minutes && <span className={styles.error}>{errors.runtime_minutes}</span>}
            </div>
          </>
        )}

        <div className={styles["form-group"]}>
          <input
            name="cast"
            placeholder={t("fields.cast")}
            value={castString}
            onChange={onChange}
          />
          {errors.cast && <span className={styles.error}>{errors.cast}</span>}
        </div>

        <div className={styles["form-group"]}>
          <input name="rating" placeholder={t("fields.rating")} value={form.rating} onChange={onChange} />
          {errors.rating && <span className={styles.error}>{errors.rating}</span>}
        </div>

        <div className={styles["form-group"]}>
          <input name="poster" placeholder={t("fields.poster")} value={form.poster} onChange={onChange} />
          {errors.poster && <span className={styles.error}>{errors.poster}</span>}
        </div>

        <div className={styles["form-group"]}>
          <input
            name="landscape_image"
            placeholder={t("fields.landscape")}
            value={form.landscape_image}
            onChange={onChange}
          />
          {errors.landscape_image && <span className={styles.error}>{errors.landscape_image}</span>}
        </div>

        {/* --- ids used to build the stream links (both Movies & TV) --- */}
        <div className={styles["form-group"]}>
          <input name="tmdb_id" placeholder={t("fields.tmdbId")} value={form.tmdb_id} onChange={onChange} />
          {errors.tmdb_id && <span className={styles.error}>{errors.tmdb_id}</span>}
        </div>

        <div className={styles["form-group"]}>
          <input name="imdb_code" placeholder={t("fields.imdbId")} value={form.imdb_code} onChange={onChange} />
          {errors.imdb_code && <span className={styles.error}>{errors.imdb_code}</span>}
        </div>

        <div className={styles["form-group"]}>
          <input
            name="trailer_clip_url"
            placeholder={t("fields.trailer")}
            value={form.trailer_clip_url}
            onChange={onChange}
          />
          {errors.trailer_clip_url && <span className={styles.error}>{errors.trailer_clip_url}</span>}
        </div>

        <div className={styles["form-group"]}>
          <input
            name="description"
            placeholder={t("fields.description")}
            value={form.description}
            onChange={onChange}
          />
        </div>

        <div className={styles["button-row"]}>
          <button type="submit" disabled={loading || Object.keys(errors).length > 0}>
            {t(`titles.${editingId ? "update" : "add"}_${mode}`)}
          </button>
          {editingId && (
            <button
              type="button"
              className={styles["reset-btn"]}
              onClick={() => {
                setForm(initialForm);
                setEditingId(null);
                setErrors({});
              }}
            >
              {t("actions.cancel")}
            </button>
          )}
        </div>
      </form>

      {loading ? (
        <BrandLoader size={64} label={t("titles.loading")} />
      ) : (
        <div className={styles["admin-table-wrapper"]}>
          <table>
            <thead>
              <tr>
                <th>{t("fields.title")}</th>
                <th>{t("titles.type")}</th>
                <th>{t("fields.genre")}</th>
                <th>{t("titles.year")}</th>
                <th>{t("users.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>{r.title}</td>
                  <td>{mode === "tv" ? t("common:kind.tv") : t("common:kind.movie")}</td>
                  <td>{r.genre}</td>
                  <td>{yearForRow(r)}</td>
                  <td>
                    <button className={styles["edit-btn"]} onClick={() => onEdit(r.id)}>
                      {t("users.edit")}
                    </button>
                    <button className={styles["delete-btn"]} onClick={() => onDelete(r.id)}>
                      {t("actions.delete")}
                    </button>
                  </td>
                </tr>
              ))}
              {!rows.length && (
                <tr>
                  <td colSpan={5} style={{ textAlign: "center", opacity: 0.7 }}>
                    {t(`titles.empty_${mode}`)}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
