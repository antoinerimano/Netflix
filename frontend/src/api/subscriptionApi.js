const API_BASE = process.env.REACT_APP_API_BASE + "/api";

function getAuthHeader() {
  const token = localStorage.getItem('access');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function createFreeSubscription(userId) {
  const res = await fetch(`${API_BASE}/users/${userId}/subscriptions/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...getAuthHeader(),
    },
    body: JSON.stringify({
      plan_id: '0',
      plan_type: 'Basic',
    }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function subscribePremium(userId, paymentMethodId) {
  const res = await fetch(`${API_BASE}/users/${userId}/subscribe/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...getAuthHeader(),
    },
    body: JSON.stringify({
      payment_method_id: paymentMethodId,
      plan_type: 'Premium',
    }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function fetchUserData(userId) {
  const res = await fetch(`${API_BASE}/users/${userId}/`, {
    headers: {
      ...getAuthHeader(),
    },
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function cancelSubscription(userId, subscriptionId) {
  const res = await fetch(
    `${API_BASE}/users/${userId}/subscriptions/${subscriptionId}/cancel/`,
    {
      method: "PUT", // <- IMPORTANT: use PUT!
      headers: {
        "Content-Type": "application/json",
        ...getAuthHeader(),
      },
    }
  );
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
