// src/components/AccountManagement.jsx
import React, { useState, useEffect, useMemo } from 'react';
import {
  fetchUserData,
  updateProfile,
  createProfile,
  deleteProfile,
  requestPasswordReset,
  requestEmailChange,
} from '../api/userApi';

import Navbar from './Navbar';
import './AccountManagement.css';
import { useParams, useNavigate } from 'react-router-dom';
import ConfirmationModal from './ConfirmationModal';

const AccountManagement = () => {
  const { userId } = useParams();
  const navigate = useNavigate();

  const avatarOptions = useMemo(
    () => ['/avatars/male.webp', '/avatars/female.webp', '/avatars/kid.webp'],
    []
  );

  const [userData, setUserData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const [editingProfileId, setEditingProfileId] = useState(null);
  const [addingNewProfile, setAddingNewProfile] = useState(false);

  const [showEmailInput, setShowEmailInput] = useState(false);
  const [newEmail, setNewEmail] = useState('');
  const [emailError, setEmailError] = useState('');

  const [newProfile, setNewProfile] = useState({
    name: '',
    age_restriction: 'G',
    language_preference: 'en',
    avatar_url: null,
    user: userId,
  });

  const [showModal, setShowModal] = useState(false);
  const [modalMessage, setModalMessage] = useState('');
  const [modalAction, setModalAction] = useState(null);

  // --- helpers ---
  const normalizeUser = (data) => {
    if (!data) return data;

    const profilesArr = Array.isArray(data.profiles)
      ? data.profiles
      : (data.profiles?.results ?? []);

    const paymentHistoryArr = Array.isArray(data.paymentHistory)
      ? data.paymentHistory
      : (data.paymentHistory?.results ?? []);

    return {
      ...data,
      profiles: profilesArr,
      paymentHistory: paymentHistoryArr,
    };
  };

  const loadUserData = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchUserData(userId);
      setUserData(normalizeUser(data));
    } catch (err) {
      setError('Failed to load user data');
    } finally {
      setLoading(false);
    }
  };

  // auth/guard
  useEffect(() => {
    const storedUserId = localStorage.getItem('userId');
    if (!storedUserId) {
      navigate('/login');
      return;
    }
    if (storedUserId !== userId) {
      setError('Not authorized to access this account');
      setLoading(false);
      return;
    }
    loadUserData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  // email change errors persisted
  useEffect(() => {
    const storedError = localStorage.getItem('emailChangeError');
    if (storedError) {
      setEmailError(storedError);
      localStorage.removeItem('emailChangeError');
    }
  }, []);

  // keep newProfile.user in sync if route changes
  useEffect(() => {
    setNewProfile((p) => ({ ...p, user: userId }));
  }, [userId]);

  // Close-first wrapper so the modal unmounts immediately, then run the async action.
  const runActionAfterClosingModal = (actionFn) => {
    setShowModal(false);
    if (typeof actionFn === 'function') {
      setTimeout(() => actionFn(), 0);
    }
  };

  // --- profile actions ---
  const handleUpdateProfile = async (profileId, updatedProfile) => {
    if (!updatedProfile.name || !updatedProfile.age_restriction || !updatedProfile.language_preference) {
      alert('All fields are required');
      return;
    }

    if (isSubmitting) return;
    setIsSubmitting(true);
    setLoading(true);

    try {
      await updateProfile(userId, profileId, updatedProfile);
      // safest: re-fetch the user so shapes always match
      await loadUserData();
      setEditingProfileId(null);
    } catch (err) {
      setError('Failed to update profile');
    } finally {
      setLoading(false);
      setIsSubmitting(false);
    }
  };

  const handleAddNewProfile = async () => {
    if (!newProfile.name || !newProfile.age_restriction || !newProfile.language_preference) {
      alert('All fields are required');
      return;
    }

    const currentProfiles = userData?.profiles ?? [];
    if (currentProfiles.length >= 4) {
      alert('You cannot add more than 4 profiles');
      return;
    }

    if (isSubmitting) return;
    setIsSubmitting(true);
    setLoading(true);

    try {
      await createProfile(userId, newProfile);
      await loadUserData();
      setAddingNewProfile(false);
      setNewProfile({
        name: '',
        age_restriction: 'G',
        language_preference: 'en',
        avatar_url: null,
        user: userId,
      });
    } catch (err) {
      setError('Failed to add new profile');
    } finally {
      setLoading(false);
      setIsSubmitting(false);
    }
  };

  const handleDeleteProfile = async (profileId) => {
    if (isSubmitting) return;
    setIsSubmitting(true);
    setLoading(true);

    try {
      await deleteProfile(userId, profileId);
      localStorage.removeItem(`userList_${profileId}`);
      await loadUserData();
    } catch (err) {
      setError('Failed to delete profile');
    } finally {
      setLoading(false);
      setIsSubmitting(false);
    }
  };

  // --- account actions ---
  const handleRequestPasswordReset = () => {
    setModalMessage('Are you sure you want to reset your password?');
    setModalAction(() => async () => {
      if (isSubmitting) return;
      setIsSubmitting(true);
      try {
        await requestPasswordReset(userData.email);
        alert('A password reset link has been sent to your email.');
      } catch (err) {
        setError('Failed to send password reset email');
      } finally {
        setIsSubmitting(false);
      }
    });
    setShowModal(true);
  };

  const handleRequestEmailChange = async () => {
    if (!showEmailInput) {
      setShowEmailInput(true);
      setEmailError('');
      return;
    }

    setModalMessage('Are you sure you want to change your email?');
    setModalAction(() => async () => {
      if (isSubmitting) return;
      setIsSubmitting(true);
      try {
        const result = await requestEmailChange(userId, newEmail);

        if (result?.error) {
          setEmailError(result.error);
        } else {
          alert('An email change confirmation has been sent to your new email.');
          setShowEmailInput(false);
          setNewEmail('');
          setEmailError('');
          window.location.reload();
        }
      } catch (err) {
        setError('Failed to request email change');
      } finally {
        setIsSubmitting(false);
      }
    });
    setShowModal(true);
  };

  const handleCancelEmailChange = () => {
    setShowEmailInput(false);
    setNewEmail('');
    setEmailError('');
  };

  // --- render guards ---
  if (loading) {
    return (
      <div className="loading-container">
        <div className="loading-spinner"></div>
      </div>
    );
  }
  if (error) return <div>Error: {error}</div>;
  if (!userData) return <div>Error: Unable to load user data.</div>;

  const profiles = userData?.profiles ?? [];

  return (
    <div>
      <Navbar />
      <div className="account-management-container">
        <h2>Account Settings</h2>

        <div className="account-section">
          <h3>Profile Information</h3>
          <div className="account-details">
            <p><strong>Name:</strong> {userData.name}</p>
            <p><strong>Email:</strong> {userData.email}</p>

            {showEmailInput && (
              <div className="email-input-container">
                <input
                  type="email"
                  className={`email-input ${emailError ? 'error-input' : ''}`}
                  placeholder="Enter new email"
                  value={newEmail}
                  onChange={(e) => {
                    setNewEmail(e.target.value);
                    setEmailError('');
                  }}
                />
                <button
                  className="change-button cancel-button"
                  onClick={handleCancelEmailChange}
                  disabled={isSubmitting}
                >
                  Cancel
                </button>
              </div>
            )}

            {emailError && <p className="error-message">{emailError}</p>}

            <button className="change-button" onClick={handleRequestEmailChange} disabled={isSubmitting}>
              {showEmailInput ? 'Confirm Email Change' : 'Change Email'}
            </button>

            <button className="change-button" onClick={handleRequestPasswordReset} disabled={isSubmitting}>
              Change Password
            </button>
          </div>
        </div>

        <div className="account-section">
          <h3>Profiles</h3>

          <div className="profiles">
            {profiles.length > 0 ? (
              profiles.map((profile) => (
                <div key={profile.id} className="profile">
                  {editingProfileId === profile.id ? (
                    <div className="profile-edit">
                      <label>
                        Name:
                        <input
                          type="text"
                          value={profile.name || ''}
                          onChange={(e) =>
                            setUserData((prev) => ({
                              ...prev,
                              profiles: prev.profiles.map((p) =>
                                p.id === profile.id ? { ...p, name: e.target.value } : p
                              ),
                            }))
                          }
                        />
                      </label>

                      <label>
                        Age Restriction:
                        <select
                          value={profile.age_restriction || 'G'}
                          onChange={(e) =>
                            setUserData((prev) => ({
                              ...prev,
                              profiles: prev.profiles.map((p) =>
                                p.id === profile.id ? { ...p, age_restriction: e.target.value } : p
                              ),
                            }))
                          }
                        >
                          <option value="G">G</option>
                          <option value="PG">PG</option>
                          <option value="PG-13">PG-13</option>
                          <option value="R">R</option>
                          <option value="NC-17">NC-17</option>
                        </select>
                      </label>

                      <label>
                        Language:
                        <select
                          value={profile.language_preference || 'en'}
                          onChange={(e) =>
                            setUserData((prev) => ({
                              ...prev,
                              profiles: prev.profiles.map((p) =>
                                p.id === profile.id ? { ...p, language_preference: e.target.value } : p
                              ),
                            }))
                          }
                        >
                          <option value="en">English</option>
                          <option value="es">Español</option>
                          <option value="fr">Français</option>
                          <option value="de">Deutsch</option>
                          <option value="zh">中文</option>
                        </select>
                      </label>

                      <label>
                        Choose Profile Picture:
                        <div className="avatar-options">
                          {avatarOptions.map((avatar, index) => (
                            <img
                              key={index}
                              src={avatar}
                              alt={`Avatar ${index + 1}`}
                              className={`avatar-option ${profile.avatar_url === avatar ? 'selected' : ''}`}
                              onClick={() =>
                                setUserData((prev) => ({
                                  ...prev,
                                  profiles: prev.profiles.map((p) =>
                                    p.id === profile.id ? { ...p, avatar_url: avatar } : p
                                  ),
                                }))
                              }
                            />
                          ))}
                        </div>
                      </label>

                      <button onClick={() => handleUpdateProfile(profile.id, profile)} disabled={isSubmitting}>
                        Save Profile
                      </button>
                      <button onClick={() => setEditingProfileId(null)} disabled={isSubmitting}>
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <div className="profile-view">
                      <img
                        src={profile.avatar_url || '/default-profile.png'}
                        alt={profile.name}
                        className="profile-avatar"
                      />
                      <div className="profile-details">
                        <p><strong>Name:</strong> {profile.name}</p>
                        <p><strong>Age Restriction:</strong> {profile.age_restriction}</p>
                        <p><strong>Language:</strong> {profile.language_preference}</p>

                        <button
                          className="profile-button"
                          onClick={() => setEditingProfileId(profile.id)}
                          disabled={isSubmitting}
                        >
                          Edit
                        </button>
                        <button
                          className="profile-button"
                          onClick={() => handleDeleteProfile(profile.id)}
                          disabled={isSubmitting}
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              ))
            ) : (
              <p>No profiles available</p>
            )}

            {addingNewProfile ? (
              <div className="profile-edit">
                <label>
                  Name:
                  <input
                    type="text"
                    value={newProfile.name}
                    onChange={(e) => setNewProfile({ ...newProfile, name: e.target.value })}
                  />
                </label>

                <label>
                  Age Restriction:
                  <select
                    value={newProfile.age_restriction}
                    onChange={(e) => setNewProfile({ ...newProfile, age_restriction: e.target.value })}
                  >
                    <option value="G">G</option>
                    <option value="PG">PG</option>
                    <option value="PG-13">PG-13</option>
                    <option value="R">R</option>
                    <option value="NC-17">NC-17</option>
                  </select>
                </label>

                <label>
                  Language:
                  <select
                    value={newProfile.language_preference}
                    onChange={(e) => setNewProfile({ ...newProfile, language_preference: e.target.value })}
                  >
                    <option value="en">English</option>
                    <option value="es">Español</option>
                    <option value="fr">Français</option>
                    <option value="de">Deutsch</option>
                    <option value="zh">中文</option>
                  </select>
                </label>

                <label>
                  Choose Profile Picture:
                  <div className="avatar-options">
                    {avatarOptions.map((avatar, index) => (
                      <img
                        key={index}
                        src={avatar}
                        alt={`Avatar ${index + 1}`}
                        className={`avatar-option ${newProfile.avatar_url === avatar ? 'selected' : ''}`}
                        onClick={() => setNewProfile({ ...newProfile, avatar_url: avatar })}
                      />
                    ))}
                  </div>
                </label>

                <button onClick={handleAddNewProfile} disabled={isSubmitting}>
                  Add Profile
                </button>
                <button onClick={() => setAddingNewProfile(false)} disabled={isSubmitting}>
                  Cancel
                </button>
              </div>
            ) : (
              <button
                className="add-profile-button"
                onClick={() => setAddingNewProfile(true)}
                disabled={isSubmitting}
              >
                Add Profile
              </button>
            )}
          </div>
        </div>
      </div>

      {showModal && (
        <ConfirmationModal
          message={modalMessage}
          onConfirm={() => runActionAfterClosingModal(modalAction)}
          onCancel={() => setShowModal(false)}
        />
      )}
    </div>
  );
};

export default AccountManagement;
