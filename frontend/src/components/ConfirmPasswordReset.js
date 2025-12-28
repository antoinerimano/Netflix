import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { confirmPasswordReset } from '../api/userApi';
import './ConfirmPasswordReset.css'; // Import CSS file

const ConfirmPasswordReset = () => {
  const { uid, token } = useParams();
  const navigate = useNavigate();
  
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const validatePassword = (password) => {
    const minLength = 8;
    const regex = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$/;
    if (password.length < minLength) return "Password must be at least 8 characters long.";
    if (!regex.test(password)) return "Password must contain uppercase, lowercase, number, and special character.";
    return null;
  };

  const handleResetPassword = async (e) => {
    e.preventDefault();
    setError('');
    setMessage('');

    const validationError = validatePassword(newPassword);
    if (validationError) {
      setError(validationError);
      return;
    }

    if (newPassword !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    try {
      setIsSubmitting(true);
      await confirmPasswordReset(uid, token, newPassword);
      setMessage("Password reset successfully! Redirecting to login...");
      setTimeout(() => navigate('/login'), 2000);
    } catch (error) {
      setError("Failed to reset password. Try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="password-reset-container">
      <div className="password-reset-box">
        <h2>Reset Your Password</h2>
        <form onSubmit={handleResetPassword}>
          <input
            type="password"
            placeholder="New password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
          />
          <input
            type="password"
            placeholder="Confirm password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
          />
          {error && <p className="error-message">{error}</p>}
          {message && <p className="success-message">{message}</p>}
          <button type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Resetting..." : "Reset Password"}
          </button>
        </form>
        <p className="back-to-login">
          <a href="/login">Back to login</a>
        </p>
      </div>
    </div>
  );
};

export default ConfirmPasswordReset;
