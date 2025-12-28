import React, { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { createProfile } from '../api/userApi'; // Import your API functions
import './CreateProfile.css'; // Import the CSS file

const CreateProfile = () => {
    const [error, setError] = useState(null);
    const location = useLocation();
    const navigate = useNavigate();
    const [loading, setLoading] = useState(false);
    const userId = localStorage.getItem('userId');
    const [newProfile, setNewProfile] = useState({
        name: '',
        age_restriction: 'G',
        language_preference: 'en',
        avatar_url: null,
        user: userId
    });

    const avatarOptions = [
        '/avatars/male.webp',
        '/avatars/female.webp',
        '/avatars/kid.webp'
        // Add more avatar URLs
    ];

    const handleAddNewProfile = async () => {
        setLoading(true);
        try {
            if (!newProfile.name || !newProfile.age_restriction || !newProfile.language_preference) {
                alert('All fields are required');
                window.location.reload();
            } else {
                navigate(`/choose-subscription`);
                const updatedUserData = await createProfile(userId, newProfile);
            }
            setLoading(false);
        } catch (err) {
            setError('Failed to add new profile');
            setLoading(false);
        }
    };

    return (
        <div className="create-profile-container">
            <h1 className="title">Create Profile</h1>
            <div className="profile-form">
                <label className="profile-label">
                    Name
                    <input
                        type="text"
                        value={newProfile.name}
                        onChange={(e) => setNewProfile({ ...newProfile, name: e.target.value })}
                        className="profile-input"
                    />
                </label>
                <label className="profile-label">
                    Age Restriction
                    <select
                        value={newProfile.age_restriction}
                        onChange={(e) => setNewProfile({ ...newProfile, age_restriction: e.target.value })}
                        className="profile-select"
                    >
                        <option value="G">G</option>
                        <option value="PG">PG</option>
                        <option value="PG-13">PG-13</option>
                        <option value="R">R</option>
                        <option value="NC-17">NC-17</option>
                    </select>
                </label>
                <label className="profile-label">
                    Language
                    <select
                        value={newProfile.language_preference}
                        onChange={(e) => setNewProfile({ ...newProfile, language_preference: e.target.value })}
                        className="profile-select"
                    >
                        <option value="en">English</option>
                        <option value="es">Español</option>
                        <option value="fr">Français</option>
                        <option value="de">Deutsch</option>
                        <option value="zh">中文</option>
                    </select>
                </label>
                <label className="profile-label">
                    Choose Profile Picture
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
                <button onClick={handleAddNewProfile} className="profile-submit-button">
                    {loading ? 'Creating...' : 'Add Profile'}
                </button>
                {error && <div className="error-message">{error}</div>}
            </div>
        </div>
    );
};

export default CreateProfile;

