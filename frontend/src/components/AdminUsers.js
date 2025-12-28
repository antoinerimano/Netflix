import React, { useEffect, useState } from "react";
import axios from "axios";
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
        alert("Failed to fetch users");
      }
    }
    setLoading(false);
  };

  const handleEdit = (user) => {
    setForm(user);
    setEditingId(user.id);
  };

  const handleDelete = async (id) => {
    if (window.confirm("Are you sure you want to delete this user?")) {
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
        alert("Failed to delete user");
      } finally {
        setLoading(false);
      }
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.name || !form.email) {
      alert("Name and email are required");
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
      alert("Failed to update user");
    } finally {
      setLoading(false);
    }
  };

  const handleChange = (e) => {
    setForm({ ...form, [e.target.name]: e.target.value });
  };

  // Handler for admin-triggered password reset
  const handleResetPassword = async (email) => {
    if (!window.confirm(`Send password reset link to ${email}?`)) return;
    try {
      await requestPasswordReset(email);
      alert(`Password reset email sent to ${email}`);
    } catch (error) {
      alert(
        "Failed to send password reset: " +
          (error?.response?.data?.error || error.message)
      );
    }
  };

  // Handler for admin-triggered email reset (asks for new email)
  const handleResetEmail = async (user) => {
    const newEmail = prompt(
      `Enter new email for ${user.name} (${user.email}):`
    );
    if (!newEmail) return;
    try {
      const result = await requestEmailChange(user.id, newEmail);
      if (result.error) {
        alert("Failed to request email change: " + result.error);
      } else {
        alert(
          "Verification link sent to new email address. The user must check their email to confirm."
        );
      }
    } catch (error) {
      alert(
        "Failed to send email change request: " +
          (error?.response?.data?.error || error.message)
      );
    }
  };

  const handleDeleteSubscription = async (user) => {
    if (
      !user.subscription ||
      !user.subscription.id ||
      !window.confirm(
        `Are you sure you want to cancel the subscription for ${user.email}?`
      )
    ) {
      return;
    }
    try {
      setLoading(true);
      await cancelSubscription(user.id, user.subscription.id);
      alert("Subscription canceled.");
      fetchUsers(); // reload and update table, button will disappear
    } catch (error) {
      alert(
        "Failed to cancel subscription: " + (error?.message || "Unknown error")
      );
    } finally {
      setLoading(false);
    }
  };

  if (!isAuthorized) {
    return (
      <div className={styles["admin-panel"]}>
        <h2>Unauthorized</h2>
        <p>You are not authorized to view this page.</p>
      </div>
    );
  }

  // Filter users based on search bar (by email)
  const filteredUsers = users.filter((u) =>
    u.email.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className={styles["admin-panel"]}>
      <h2>Admin Users</h2>
      {/* --- SEARCH BAR --- */}
      <input
        type="text"
        placeholder="Search by email..."
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
            placeholder="Name"
            value={form.name || ""}
            onChange={handleChange}
          />
          <input
            name="email"
            placeholder="Email"
            value={form.email || ""}
            onChange={handleChange}
            type="email"
          />
          <button type="submit">Update User</button>
          <button
            type="button"
            onClick={() => {
              setForm({});
              setEditingId(null);
            }}
          >
            Cancel
          </button>
        </form>
      )}

      {loading ? (
        <p>Loading users...</p>
      ) : (
        <div className={styles["admin-table-wrapper"]}>
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Staff</th>
                <th>Active</th>
                <th>Joined</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredUsers.map((u) => (
                <tr key={u.id}>
                  <td>{u.name}</td>
                  <td>{u.email}</td>
                  <td>{u.is_staff ? "Yes" : "No"}</td>
                  <td>{u.is_active ? "Yes" : "No"}</td>
                  <td>{u.created_at ? u.created_at.split("T")[0] : ""}</td>
                  <td>
                    <button
                      className={styles["edit-btn"]}
                      onClick={() => handleEdit(u)}
                      disabled={loading}
                    >
                      Edit
                    </button>
                    <button
                      className={styles["delete-btn"]}
                      onClick={() => handleDelete(u.id)}
                      disabled={loading}
                    >
                      Delete
                    </button>
                    <button
                      className={styles["reset-btn"]}
                      onClick={() => handleResetPassword(u.email)}
                      disabled={loading}
                    >
                      Reset Password
                    </button>
                    <button
                      className={styles["reset-btn"]}
                      onClick={() => handleResetEmail(u)}
                      disabled={loading}
                    >
                      Reset Email
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
                          title="Delete Subscription"
                          disabled={loading}
                        >
                          Delete Subscription
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
