// ChooseSubscription.jsx
import React, { useState, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { fetchUserData, createFreeSubscription } from '../api/subscriptionApi';
import ConfirmationModal from './ConfirmationModal';
import './ChooseSubscription.css';

const ChooseSubscription = () => {
  const location = useLocation();
  const userId = localStorage.getItem('userId');
  const jwtToken = localStorage.getItem('access'); // JWT for protected APIs

  const [userData, setUserData] = useState(null);
  const [selectedPlan, setSelectedPlan] = useState(null); // 'free' only now
  const [showConfirmationModal, setShowConfirmationModal] = useState(false);
  const [redirecting, setRedirecting] = useState(false);

  useEffect(() => {
    // Optional: still fetch user data if you show name/email somewhere
    const fetchData = async () => {
      try {
        const data = await fetchUserData(userId, jwtToken);
        setUserData(data);
      } catch (err) {
        console.error('Failed to fetch user data:', err);
      }
    };
    if (userId && jwtToken) fetchData();
  }, [userId, jwtToken]);

  const handleChooseSubscription = () => {
    setSelectedPlan('free');
    setShowConfirmationModal(true);
  };

  const handleConfirmFreePlan = async () => {
    setRedirecting(true);
    try {
      await createFreeSubscription(userId, jwtToken);
      window.location.href = '/login'; // Redirect to login after choosing free plan
    } catch (err) {
      setRedirecting(false);
      alert('Failed to choose subscription: ' + err.message);
    }
  };

  if (redirecting) {
    return (
      <div className="choose-subscription-page">
        <h2 className="subscription-title">Redirecting...</h2>
        <p>You will be redirected shortly. Please wait while we process your subscription.</p>
      </div>
    );
  }

  return (
    <div className="choose-subscription-page">
      <h2 className="subscription-title">Choose Your Subscription</h2>

      <div className="subscription-options">
        {/* Only Free plan remains */}
        <div
          className={`subscription-option ${selectedPlan === 'free' ? 'selected' : ''}`}
          onClick={handleChooseSubscription}
        >
          <h3>Free Plan</h3>
          <p>$0.00/month</p>
          <div className="subscription-badge">Free</div>
        </div>
      </div>

      {showConfirmationModal && selectedPlan === 'free' && (
        <ConfirmationModal
          message="Are you sure you want to choose the free plan?"
          onConfirm={handleConfirmFreePlan}
          onCancel={() => setShowConfirmationModal(false)}
        />
      )}
    </div>
  );
};

export default ChooseSubscription;
