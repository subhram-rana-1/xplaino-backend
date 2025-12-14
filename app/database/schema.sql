-- MariaDB Schema for Caten Application
-- This file defines the database tables for user authentication and session management

-- User table
CREATE TABLE IF NOT EXISTS user (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Google user authentication info table
CREATE TABLE IF NOT EXISTS google_user_auth_info (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    user_id CHAR(36) NOT NULL,
    iss VARCHAR(256),
    sub VARCHAR(256),
    email VARCHAR(256),
    email_verified BOOLEAN,
    given_name VARCHAR(256),
    family_name VARCHAR(256),
    picture VARCHAR(2000),
    locale VARCHAR(256),
    azp VARCHAR(256),
    aud VARCHAR(256),
    iat VARCHAR(256),
    exp VARCHAR(256),
    jti VARCHAR(256),
    alg VARCHAR(256),
    kid VARCHAR(256),
    typ VARCHAR(256),
    hd VARCHAR(256),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_sub (sub),
    INDEX idx_user_id (user_id),
    FOREIGN KEY (user_id) REFERENCES user(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- User session table
CREATE TABLE IF NOT EXISTS user_session (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    auth_vendor_type ENUM('GOOGLE') NOT NULL,
    auth_vendor_id CHAR(36) NOT NULL,
    access_token_state ENUM('VALID', 'INVALID') NOT NULL DEFAULT 'VALID',
    refresh_token VARCHAR(256) NOT NULL,
    refresh_token_expires_at TIMESTAMP NOT NULL,
    access_token_expires_at TIMESTAMP NOT NULL DEFAULT (CURRENT_TIMESTAMP + INTERVAL 24 HOUR),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_refresh_token (refresh_token),
    INDEX idx_auth_vendor (auth_vendor_type, auth_vendor_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Unauthenticated user API usage table
CREATE TABLE IF NOT EXISTS unauthenticated_user_api_usage (
    user_id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    api_usage JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Saved words table
CREATE TABLE IF NOT EXISTS saved_word (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    word VARCHAR(32) NOT NULL,
    source_url VARCHAR(1024) NOT NULL,
    user_id CHAR(36) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_user_created_at (user_id, created_at),
    FOREIGN KEY (user_id) REFERENCES user(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

