import React, { useState, useContext } from 'react';
import { useNavigate } from 'react-router-dom'; // Import useNavigate
import { loginUser, registerUser } from '../api/userApi'; // Adjust the import path if necessary
import './Register.css'; // Import the CSS file for styling
import { AuthContext } from './AuthContext';

const Register = () => {
    const [name, setName] = useState('');
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');
    const [error, setError] = useState(null);
    const [loading, setLoading] = useState(false); // Add loading state
    const { setIsAuthenticated } = useContext(AuthContext);

    const navigate = useNavigate(); // Initialize useNavigate

    const handleSubmit = async (e) => {
        e.preventDefault();

        if (password !== confirmPassword) {
            setError('Passwords do not match');
            return;
        }

        setLoading(true); // Start loading
        setError(null); // Clear previous errors

        try {
            const data = await registerUser(name, email, password);
            console.log('Registration successful:', data);
            const login = await loginUser(email, password);
            localStorage.setItem('access', data.access);
            localStorage.setItem('refresh', data.refresh);
            localStorage.setItem('userId', data.user.id);
            setIsAuthenticated(true);
            const id = data.user.id;
            // Redirect to the create-profile page after successful registration
            navigate(`/create-profile`, { state: { userId: id } });
        } catch (err) {
            if (err.message === 'This email is already registered') {
                setError('This email is already registered. Please use a different email.');
            } else {
                setError(err.message || 'Registration failed. Please try again.');
            }
        } finally {
            setLoading(false); // Stop loading
        }
    };



    return (
        <div className="register-page">
            <div className="register-container">
                <h2 className="register-title">Sign Up</h2>
                {error && <p className="error-message">{error}</p>}
                <form onSubmit={handleSubmit} className="register-form">
                    <input
                        type="text"
                        placeholder="Name"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        required
                        className="register-input"
                    />
                    <input
                        type="email"
                        placeholder="Email"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        required
                        className="register-input"
                    />
                    <input
                        type="password"
                        placeholder="Password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        required
                        className="register-input"
                    />
                    <input
                        type="password"
                        placeholder="Confirm Password"
                        value={confirmPassword}
                        onChange={(e) => setConfirmPassword(e.target.value)}
                        required
                        className="register-input"
                    />
                    <button type="submit" className="register-button" disabled={loading}>
                        {loading ? 'Registering...' : 'Sign Up'}
                    </button>
                </form>
                <p className="login-redirect">
                    Already have an account? <a href="/login">Log In</a>
                </p>
            </div>
        </div>
    );
};

export default Register;

