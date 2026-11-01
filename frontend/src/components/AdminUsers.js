import React, { useEffect, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { formatDate } from "../i18n/format";
import {
  requestPasswordReset,
  requestEmailChange,
  fetchUserData,      // to refetch user data after deleting subscription
} from "../api/userApi";
import { cancelSubscription } from "../api/subscriptionApi"; // to delete subscription
import styles from "./AdminPanel.module.css";

const API_BASE_URL = "http://localhost:8000/api";

const getAuthHeader = () => {
  const token = localStorage.getItem("access");
  return token ? { Authorization: `Bearer ${token}` } : {};
};

const AdminUsers = () => {
  const { t } = useTranslation("admin");
  const [users, setUsers] = useState([]);
  const [form, setForm] = useState({});
  const [editingId, setEditingId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [isAuthorized, setIsAuthorized] = useState(true);
  const [search, setSearch] = useState("");

  useEffect(() => {
    fetchUsers();
    // eslint-disable-next-line
  }, []);

  const fetchUsers = async () => {
    setLoading(true);
    try {
      const response = await axios.get(`${API_BASE_URL}/users/`, {
        headers: getAuthHeader(),
      });

      // For each user, fetch their subscription info
      const usersWithSubs = await Promise.all(
        response.data.map(async (u) => {
          try {
            const userData = await fetchUserData(u.id);
            return { ...u, subscription: userData.subscription };
          } catch {
            return { ...u, subscription: null };
          }
        })
      );
      setUsers(usersWithSubs);
      setIsAuthorized(true);
    } catch (error) {
      if (
        error.response &&
        (error.response.status === 401 || error.response.status === 403)
      ) {
        setIsAuthorized(false);
      } else {
        alert(t("users.fetchFailed"));
      }
    }
    setLoading(false);
  };

  const handleEdit = (user) => {
    setForm(user);
    setEditingId(user.id);
  };

  const handleDelete = async (id) => {
    if (window.confirm(t("users.confirmDelete"))) {
      try {
        setLoading(true);
        await axios.delete(`${API_BASE_URL}/users/${id}/`, {
          headers: getAuthHeader(),
        });
        setUsers((prev) => prev.filter((u) => u.id !== id));
        if (editingId === id) {
          setForm({});
          setEditingId(null);
        }
      } catch (error) {
        alert(t("users.deleteFailed"));
      } finally {
        setLoading(false);
      }
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.name || !form.email) {
      alert(t("users.required"));
      return;
    }
    try {
      setLoading(true);
      const response = await axios.put(
        `${API_BASE_URL}/users/${editingId}/`,
        form,
        { headers: getAuthHeader() }
      );
      setUsers((prev) =>
        prev.map((u) => (u.id === editingId ? response.data : u))
      );
      setForm({});
      setEditingId(null);
    } catch (error) {
      alert(t("users.updateFailed"));
    } finally {
      setLoading(false);
    }
  };

  const handleChange = (e) => {
    setForm({ ...form, [e.target.name]: e.target.value });
  };

  // Handler for admin-triggered password reset
  const handleResetPassword = async (email) => {
    if (!window.confirm(t("users.confirmReset", { email }))) return;
    try {
      await requestPasswordReset(email);
      alert(t("users.resetSent", { email }));
    } catch (error) {
      alert(t("users.resetFailed", { reason: error?.response?.data?.error || error.message }));
    }
  };

  // Handler for admin-triggered email reset (asks for new email)
  const handleResetEmail = async (user) => {
    const newEmail = prompt(t("users.promptEmail", { name: user.name, email: user.email }));
    if (!newEmail) return;
    try {
      const result = await requestEmailChange(user.id, newEmail);
      if (result.error) {
        alert(t("users.emailFailed", { reason: result.error }));
      } else {
        alert(t("users.emailSent"));
      }
    } catch (error) {
      alert(t("users.emailFailed", { reason: error?.response?.data?.error || error.message }));
    }
  };

  const handleDeleteSubscription = async (user) => {
    if (
      !user.subscription ||
      !user.subscription.id ||
      !window.confirm(t("users.confirmCancelSub", { email: user.email }))
    ) {
      return;
    }
    try {
      setLoading(true);
      await cancelSubscription(user.id, user.subscription.id);
      alert(t("users.subCanceled"));
      fetchUsers(); // reload and update table, button will disappear
    } catch (error) {
      alert(t("users.subCancelFailed", { reason: error?.message || "" }));
    } finally {
      setLoading(false);
    }
  };

  if (!isAuthorized) {
    return (
      <div className={styles["admin-panel"]}>
        <h2>{t("unauthorized")}</h2>
        <p>{t("unauthorizedText")}</p>
      </div>
    );
  }

  // Filter users based on search bar (by email)
  const filteredUsers = users.filter((u) =>
    u.email.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className={styles["admin-panel"]}>
      <h2>{t("common:nav.adminUsers")}</h2>
      {/* --- SEARCH BAR --- */}
      <input
        type="text"
        placeholder={t("users.search")}
        value={search}
        onChange={e => setSearch(e.target.value)}
        style={{
          marginBottom: 16,
          padding: 8,
          borderRadius: 4,
          border: "1px solid #ccc",
          width: "100%",
          maxWidth: 350,
        }}
      />
      {/* Only show the form if editing */}
      {editingId && (
        <form onSubmit={handleSubmit} style={{ marginBottom: "24px" }}>
          <input
            name="name"
            placeholder={t("auth:fields.name")}
            value={form.name || ""}
            onChange={handleChange}
          />
          <input
            name="email"
            placeholder={t("auth:fields.email")}
            value={form.email || ""}
            onChange={handleChange}
            type="email"
          />
          <button type="submit">{t("users.update")}</button>
          <button
            type="button"
            onClick={() => {
              setForm({});
              setEditingId(null);
            }}
          >
            {t("actions.cancel")}
          </button>
        </form>
      )}

      {loading ? (
        <p>{t("users.loading")}</p>
      ) : (
        <div className={styles["admin-table-wrapper"]}>
          <table>
            <thead>
              <tr>
                <th>{t("auth:fields.name")}</th>
                <th>{t("auth:fields.email")}</th>
                <th>{t("users.staff")}</th>
                <th>{t("users.active")}</th>
                <th>{t("users.joined")}</th>
                <th>{t("users.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {filteredUsers.map((u) => (
                <tr key={u.id}>
                  <td>{u.name}</td>
                  <td>{u.email}</td>
                  <td>{u.is_staff ? t("yes") : t("no")}</td>
                  <td>{u.is_active ? t("yes") : t("no")}</td>
                  <td>{u.created_at ? formatDate(u.created_at) : ""}</td>
                  <td>
                    <button
                      className={styles["edit-btn"]}
                      onClick={() => handleEdit(u)}
                      disabled={loading}
                    >
                      {t("users.edit")}
                    </button>
                    <button
                      className={styles["delete-btn"]}
                      onClick={() => handleDelete(u.id)}
                      disabled={loading}
                    >
                      {t("actions.delete")}
                    </button>
                    <button
                      className={styles["reset-btn"]}
                      onClick={() => handleResetPassword(u.email)}
                      disabled={loading}
                    >
                      {t("users.resetPassword")}
                    </button>
                    <button
                      className={styles["reset-btn"]}
                      onClick={() => handleResetEmail(u)}
                      disabled={loading}
                    >
                      {t("users.resetEmail")}
                    </button>
                    {/* ---- SHOW ONLY FOR ACTIVE PREMIUM ---- */}
                    {u.subscription &&
                      u.subscription.id &&
                      u.subscription.plan_type === "Premium" &&
                      u.subscription.status === "Active" && (
                        <button
                          className={styles["delete-btn"]}
                          style={{ background: "#fd7676" }}
                          onClick={() => handleDeleteSubscription(u)}
                          title={t("users.deleteSub")}
                          disabled={loading}
                        >
                          {t("users.deleteSub")}
                        </button>
                      )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

export default AdminUsers;
