import React, { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import Navbar from "./Navbar";
import MovieCard from "./MovieCard";
import "./List.css";
import { fetchTitlesByActorTmdbId } from "../api/titlesApi";

const ActorDetail = () => {
  const { tmdbId } = useParams();
  const navigate = useNavigate();

  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setErr("");

    fetchTitlesByActorTmdbId(tmdbId)
      .then((data) => {
        if (!alive) return;
        setItems(Array.isArray(data) ? data : []);
      })
      .catch((e) => {
        if (!alive) return;
        setErr(e?.message || "Failed to load actor titles");
      })
      .finally(() => {
        if (!alive) return;
        setLoading(false);
      });

    return () => {
      alive = false;
    };
  }, [tmdbId]);

  const getDetailPath = (item) => {
    const isTv =
      String(item?.type || "").toLowerCase() === "tv" ||
      !!item?.first_air_date;
    return `/${isTv ? "tv" : "movies"}/${item?.id}`;
  };

  if (loading) {
    return (
      <div className="loading-container">
        <div className="loading-spinner"></div>
      </div>
    );
  }

  return (
    <div>
      <Navbar />
      <div style={{ padding: 16 }}>
        {err ? <p>{err}</p> : null}

        <h2 style={{ margin: "12px 0" }}>Actor</h2>

        <div className="ps-store-movie-grid">
          {items.length ? (
            items.map((it, idx) => (
              <MovieCard
                key={`${it.id}-${idx}`}
                movie={it}
                analytics={{
                  surface: "actor_page",
                  position: idx,
                  row_title: "Actor titles",
                }}
                onClick={() => navigate(getDetailPath(it))}
              />
            ))
          ) : (
            <p>No titles found for this actor.</p>
          )}
        </div>
      </div>
    </div>
  );
};

export default ActorDetail;
