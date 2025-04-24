# Authentication System Documentation

## Overview

The AlgoLens platform implements a robust authentication system with role-based access control (RBAC). The system consists of both frontend and backend components working together to provide secure user authentication and authorization.

## User Roles

The system supports three distinct user roles:

1. `general_member` - Basic access level for regular team members
2. `team_lead` - Elevated access for team leaders (Currently team_lead have the same privilges as general_member but this can change in the future.)
3. `exec_board` - Highest access level for executive board members

## Authentication Flow

### Login Process

1. Users enter their credentials (email and password) on the login page
2. The system validates credentials against the database
3. Upon successful authentication:
   - A JWT access token is generated (valid for 12 hours)
   - User information is stored in localStorage
   - User is redirected based on their `force_password_change` status:
     - If true: Redirected to profile page
     - If false: Redirected to dashboard

### Registration Process

1. Only executive board members can register new users
2. Required fields for registration:
   - Email (must be unique)
   - Password (must meet security requirements)
   - First Name
   - Last Name
   - Team
   - Role (optional, defaults to `general_member`)

## Password Requirements

Passwords must meet the following criteria:

- Minimum 8 characters
- Maximum 100 characters
- At least one uppercase letter
- At least one lowercase letter
- At least one digit
- At least one special character
- No spaces allowed

## Security Features

1. **JWT-based Authentication**

   - Access tokens are used for API authorization
   - Tokens include user ID, email, role, and force_password_change status
   - Tokens expire after 12 hours

2. **Password Security**

   - Passwords are hashed using secure hashing algorithms
   - Password validation on both frontend and backend
   - Force password change feature for new users

3. **Role-Based Access Control**
   - Protected routes using `@roles_required` decorator
   - Frontend route protection based on user role
   - Executive board members have access to user management features

## Frontend Components

### Authentication Context

- Manages global authentication state
- Provides user information throughout the application
- Handles login/logout state persistence

### Key Pages

1. **Login Page** (`/`)

   - Entry point for user authentication
   - Handles credential validation
   - Manages redirects based on user state

2. **Registration Page** (`/signup`)

   - Accessible only to executive board members
   - Form for creating new user accounts
   - Validates all required fields

3. **Profile Page** (`/profile`)

   - User profile management
   - Password change functionality
   - Personal information updates

4. **Users Page** (`/users`)
   - Accessible only to executive board members
   - User management interface
   - User role and status updates

## Backend Implementation

### Authentication Routes

1. `/auth/login`

   - Handles user authentication
   - Returns JWT token and force_password_change status

2. `/auth/register`
   - Protected route (exec_board only)
   - Creates new user accounts
   - Validates user data

### Database Schema

The `users` table in the `auth` schema contains:

- User ID (primary key)
- Email (unique)
- Password hash
- First Name
- Last Name
- Team
- Role
- Created At timestamp
- Force Password Change flag

## Error Handling

The system provides clear error messages for:

- Invalid credentials
- Missing required fields
- Duplicate email addresses
- Insufficient permissions
- Invalid password format

## Session Management

- User sessions are maintained using JWT tokens
- Tokens are stored in localStorage
- Automatic logout on token expiration
- Manual logout functionality available
