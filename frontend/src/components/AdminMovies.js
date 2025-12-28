// src/components/AdminMovies.js
import React, { useEffect, useMemo, useState } from "react";
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
  video_url: "",
  trailer_clip_url: "",
  movie_link2: "",
  movie_link3: "",
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
    if (!data.title || data.title.trim().length < 2) e.title = "Title is required (min 2 chars)";
    if (!data.genre || data.genre.trim().length < 2) e.genre = "Genre is required";
    if (!data.rating || isNaN(Number(data.rating))) e.rating = "Rating must be a number";
    if (!data.cast || !Array.isArray(data.cast) || !data.cast.length || !data.cast[0]) {
      e.cast = "Cast is required (comma separated)";
    }

    // Movie-only validation
    if (mode === "movie") {
      if (!data.director || data.director.trim().length < 2) e.director = "Director is required";
      if (data.runtime_minutes && isNaN(Number(data.runtime_minutes))) {
        e.runtime_minutes = "Runtime must be a number";
      }
      if (!data.release_date || !isValidYyyyOrIso(data.release_date)) {
        e.release_date = "Valid year (YYYY) or date (YYYY-MM-DD) required";
      }
    }

    // TV-only validation
    if (mode === "tv") {
      if (!data.first_air_date || !isValidYyyyOrIso(data.first_air_date)) {
        e.first_air_date = "Valid year (YYYY) or date (YYYY-MM-DD) required";
      }
    }

    // URL checks (validate when present)
    if (!isValidUrl(data.poster)) e.poster = "Poster URL is invalid";
    if (!isValidUrl(data.landscape_image)) e.landscape_image = "Landscape image URL is invalid";
    if (!isValidUrl(data.video_url)) e.video_url = "Video URL is invalid";
    if (!isValidUrl(data.trailer_clip_url)) e.trailer_clip_url = "Trailer clip URL is invalid";
    if (!isValidUrl(data.movie_link2)) e.movie_link2 = "Movie link 2 URL is invalid";
    if (!isValidUrl(data.movie_link3)) e.movie_link3 = "Movie link 3 URL is invalid";

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
      video_url: data.video_url || "",
      movie_link2: data.movie_link2 || "",
      movie_link3: data.movie_link3 || "",
    });
    setEditingId(id);
  };

  const onDelete = async (id) => {
    if (!window.confirm(`Delete this ${mode === "movie" ? "movie" : "TV show"}?`)) return;
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

    let submit = { ...form };

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
        <h2>Admin Titles (Movies & TV)</h2>
        <div>
          <button
            type="button"
            className={mode === "movie" ? styles["edit-btn"] : styles["reset-btn"]}
            onClick={() => setMode("movie")}
          >
            Movies
          </button>
          <button
            type="button"
            style={{ marginLeft: 8 }}
            className={mode === "tv" ? styles["edit-btn"] : styles["reset-btn"]}
            onClick={() => setMode("tv")}
          >
            TV
          </button>
        </div>
      </div>

      <form onSubmit={onSubmit} className={styles["admin-form"]}>
        <div className={styles["form-group"]}>
          <input name="title" placeholder="Title" value={form.title} onChange={onChange} />
          {errors.title && <span className={styles.error}>{errors.title}</span>}
        </div>

        {mode === "movie" ? (
          <div className={styles["form-group"]}>
            <input
              name="release_date"
              placeholder="Release Year or Date (YYYY or YYYY-MM-DD)"
              value={form.release_date}
              onChange={onChange}
            />
            {errors.release_date && <span className={styles.error}>{errors.release_date}</span>}
          </div>
        ) : (
          <div className={styles["form-group"]}>
            <input
              name="first_air_date"
              placeholder="First Air Year or Date (YYYY or YYYY-MM-DD)"
              value={form.first_air_date}
              onChange={onChange}
            />
            {errors.first_air_date && <span className={styles.error}>{errors.first_air_date}</span>}
          </div>
        )}

        <div className={styles["form-group"]}>
          <input name="genre" placeholder="Genre" value={form.genre} onChange={onChange} />
          {errors.genre && <span className={styles.error}>{errors.genre}</span>}
        </div>

        {/* Movie-only fields */}
        {mode === "movie" && (
          <>
            <div className={styles["form-group"]}>
              <input
                name="director"
                placeholder="Director"
                value={form.director}
                onChange={onChange}
              />
              {errors.director && <span className={styles.error}>{errors.director}</span>}
            </div>

            <div className={styles["form-group"]}>
              <input
                name="runtime_minutes"
                placeholder="Runtime (minutes)"
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
            placeholder="Cast (comma separated)"
            value={castString}
            onChange={onChange}
          />
          {errors.cast && <span className={styles.error}>{errors.cast}</span>}
        </div>

        <div className={styles["form-group"]}>
          <input name="rating" placeholder="Rating" value={form.rating} onChange={onChange} />
          {errors.rating && <span className={styles.error}>{errors.rating}</span>}
        </div>

        <div className={styles["form-group"]}>
          <input name="poster" placeholder="Poster URL" value={form.poster} onChange={onChange} />
          {errors.poster && <span className={styles.error}>{errors.poster}</span>}
        </div>

        <div className={styles["form-group"]}>
          <input
            name="landscape_image"
            placeholder="Landscape Image URL"
            value={form.landscape_image}
            onChange={onChange}
          />
          {errors.landscape_image && <span className={styles.error}>{errors.landscape_image}</span>}
        </div>

        {/* --- 4 link fields (both Movies & TV) --- */}
        <div className={styles["form-group"]}>
          <input
            name="video_url"
            placeholder="Main Video URL"
            value={form.video_url}
            onChange={onChange}
          />
          {errors.video_url && <span className={styles.error}>{errors.video_url}</span>}
        </div>

        <div className={styles["form-group"]}>
          <input
            name="trailer_clip_url"
            placeholder="Trailer Clip URL"
            value={form.trailer_clip_url}
            onChange={onChange}
          />
          {errors.trailer_clip_url && <span className={styles.error}>{errors.trailer_clip_url}</span>}
        </div>

        <div className={styles["form-group"]}>
          <input
            name="movie_link2"
            placeholder="Movie Link 2 (optional)"
            value={form.movie_link2}
            onChange={onChange}
          />
          {errors.movie_link2 && <span className={styles.error}>{errors.movie_link2}</span>}
        </div>

        <div className={styles["form-group"]}>
          <input
            name="movie_link3"
            placeholder="Movie Link 3 (optional)"
            value={form.movie_link3}
            onChange={onChange}
          />
          {errors.movie_link3 && <span className={styles.error}>{errors.movie_link3}</span>}
        </div>
        {/* --- end link fields --- */}

        <div className={styles["form-group"]}>
          <input
            name="description"
            placeholder="Description"
            value={form.description}
            onChange={onChange}
          />
        </div>

        <div className={styles["button-row"]}>
          <button type="submit" disabled={loading || Object.keys(errors).length > 0}>
            {editingId ? "Update" : "Add"} {mode === "movie" ? "Movie" : "TV Show"}
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
              Cancel
            </button>
          )}
        </div>
      </form>

      {loading ? (
        <p>Loading…</p>
      ) : (
        <div className={styles["admin-table-wrapper"]}>
          <table>
            <thead>
              <tr>
                <th>Title</th>
                <th>Type</th>
                <th>Genre</th>
                <th>Year</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>{r.title}</td>
                  <td>{mode.toUpperCase()}</td>
                  <td>{r.genre}</td>
                  <td>{yearForRow(r)}</td>
                  <td>
                    <button className={styles["edit-btn"]} onClick={() => onEdit(r.id)}>
                      Edit
                    </button>
                    <button className={styles["delete-btn"]} onClick={() => onDelete(r.id)}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
              {!rows.length && (
                <tr>
                  <td colSpan={5} style={{ textAlign: "center", opacity: 0.7 }}>
                    No {mode === "movie" ? "movies" : "TV shows"} yet.
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
