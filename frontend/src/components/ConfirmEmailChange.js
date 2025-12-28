// src/components/ConfirmEmailChange.jsx
import React, { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { confirmEmailChange } from "../api/userApi";
import './ConfirmEmailChange.css';

export default function ConfirmEmailChange() {
  const navigate = useNavigate();
  const { userId: userIdFromPath, token: tokenFromPath } = useParams();
  const [searchParams] = useSearchParams();

  // support either path (/.../:userId/:token) or query (?u=...&t=...)
  const userId = userIdFromPath || searchParams.get("u") || searchParams.get("userId");
  const token  = tokenFromPath  || searchParams.get("t") || searchParams.get("token");

  const [message, setMessage] = useState("Updating your email...");

  useEffect(() => {
    (async () => {
      if (!userId || !token) {
        console.error("Missing userId/token", { userId, token });
        setMessage("Invalid confirmation link.");
        return;
      }
      try {
        await confirmEmailChange(userId, token); // <-- must pass userId
        setMessage("Your email has been updated. Redirecting…");
        setTimeout(() => navigate(`/login`), 1500);
      } catch (e) {
        const err = e?.response?.data?.error || e?.message || "Failed to update email.";
        setMessage(String(err));
      }
    })();
  }, [userId, token, navigate]);

  return <div className="confirm-email-container">
    <p className="confirm-email-message">{message}</p>
  </div>;
}
