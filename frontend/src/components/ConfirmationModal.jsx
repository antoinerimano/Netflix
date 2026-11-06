import React from 'react';
import './ConfirmationModal.css'; // Import your custom styles

const ConfirmationModal = ({ message, onConfirm, onCancel }) => {
    return (
        <div className="modal-overlay">
            <div className="modal-content">
                <h3>Confirm Your Choice</h3>
                <p>{message}</p>
                <div className="modal-actions">
                    <button className="modal-button confirm" onClick={onConfirm}>Yes, proceed</button>
                    <button className="modal-button cancel" onClick={onCancel}>Cancel</button>
                </div>
            </div>
        </div>
    );
};

export default ConfirmationModal;
