// src/pages/NotFound.js
// Unknown address: the app's frame (navbar) and a way back, instead of a blank black page.
import React from 'react';
import { useNavigate } from 'react-router-dom';
import Navbar from '../components/Navbar';
import { Button, EmptyState } from '../design';
import { SearchIcon } from '../design/icons';

export default function NotFound() {
  const navigate = useNavigate();
  return (
    <div className="homepage">
      <Navbar />
      <EmptyState
        page
        icon={<SearchIcon />}
        title="Page not found"
        actions={
          <>
            <Button variant="primary" to="/">Go home</Button>
            <Button variant="ghost" onClick={() => navigate(-1)}>Go back</Button>
          </>
        }
      >
        This page doesn't exist or has moved.
      </EmptyState>
    </div>
  );
}
