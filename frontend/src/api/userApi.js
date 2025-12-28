// userApi.js
import http from "./http";

// ---------- User + Account ----------
export const fetchUserData = async (userId) => {
  const userResponse = await http.get(`/users/${encodeURIComponent(userId)}/`);
  const user = userResponse.data;

  const profilesResponse = await http.get(`/users/${encodeURIComponent(userId)}/profiles/`);
  const paymentHistoryResponse = await http.get(`/users/${encodeURIComponent(userId)}/payment_history/`);

  return {
    ...user,
    profiles: profilesResponse.data,
    paymentHistory: paymentHistoryResponse.data,
  };
};

export const fetchUserProfiles = async (userId) => {
  const res = await http.get(`/users/${encodeURIComponent(userId)}/profiles/`);
  return res.data;
};

export const fetchUserProfile = async (userId, profileId) => {
  const res = await http.get(
    `/users/${encodeURIComponent(userId)}/profiles/${encodeURIComponent(profileId)}/`
  );
  return res.data;
};

// ---------- Profiles CRUD ----------
export const updateProfile = async (userId, profileId, updatedProfile) => {
  const res = await http.put(
    `/users/${encodeURIComponent(userId)}/profiles/${encodeURIComponent(profileId)}/`,
    updatedProfile
  );
  return res.data;
};

export const createProfile = async (userId, newProfile) => {
  const res = await http.post(`/users/${encodeURIComponent(userId)}/profiles/`, newProfile);
  return res.data;
};

export const deleteProfile = async (userId, profileId) => {
  const res = await http.delete(
    `/users/${encodeURIComponent(userId)}/profiles/${encodeURIComponent(profileId)}/`
  );
  return res.data;
};

// Mark profile active (your backend uses PATCH for this)
export const setCurrentProfile = async (userId, profileId) => {
  const res = await http.patch(
    `/users/${encodeURIComponent(userId)}/profiles/${encodeURIComponent(profileId)}/`,
    { is_active: true }
  );
  return res.data;
};

// ---------- Subscription ----------
export const fetchUserSubscriptionStatus = async (userId) => {
  try {
    const res = await http.get(`/users/${encodeURIComponent(userId)}/subscriptions/`);

    const isSubscribed = Array.isArray(res.data) && res.data.some(
      (sub) => sub.plan_type === "Premium" && sub.status === "Active"
    );

    return { subscribed: isSubscribed };
  } catch (error) {
    console.error("Error fetching subscription status:", error?.response?.data || error.message);
    return { subscribed: false };
  }
};

// ---------- Auth ----------
export const loginUser = async (email, password) => {
  const res = await http.post(`/users/login/`, { email, password });
  return res.data;
};

export const registerUser = async (name, email, password) => {
  try {
    const res = await http.post(`/users/register/`, { name, email, password });
    return res.data;
  } catch (error) {
    const data = error?.response?.data;
    const status = error?.response?.status;

    if (status === 400 && data?.error === "This email is already registered") {
      throw new Error("This email is already registered");
    }
    throw new Error("Failed to register user");
  }
};

// ---------- Password reset ----------
export const requestPasswordReset = async (email) => {
  const res = await http.post(`/password-reset/`, { email });
  return res.data;
};

export const confirmPasswordReset = async (uid, token, newPassword) => {
  const res = await http.post(`/password-reset-confirm/`, {
    uid,
    token,
    new_password: newPassword,
  });
  return res.data;
};

// ---------- Email change ----------
export const requestEmailChange = async (userId, newEmail) => {
  try {
    const res = await http.post(
      `/users/${encodeURIComponent(userId)}/request-email-change/`,
      { new_email: newEmail }
    );
    return res.data;
  } catch (error) {
    console.error("Error requesting email change:", error?.response?.data || error.message);
    if (error?.response) {
      return { error: error.response.data?.error || "An unknown error occurred" };
    }
    return { error: "Network error. Please try again." };
  }
};

export const confirmEmailChange = async (userId, token) => {
  const res = await http.post(
    `/users/${encodeURIComponent(userId)}/confirm-email-change/`,
    { token: decodeURIComponent(token) }
  );
  return res.data;
};
