-- MariaDB Schema for Caten Application
-- This file defines the database tables for user authentication and session management

-- User table
CREATE TABLE IF NOT EXISTS user (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    role ENUM('ADMIN', 'SUPER_ADMIN') NULL,
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
    contextual_meaning VARCHAR(1000) NOT NULL,
    user_id CHAR(36) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_user_created_at (user_id, created_at),
    FOREIGN KEY (user_id) REFERENCES user(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Folder table
CREATE TABLE IF NOT EXISTS folder (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    name VARCHAR(50) NOT NULL,
    type ENUM('PAGE', 'PARAGRAPH') NOT NULL,
    parent_id CHAR(36) NULL,
    user_id CHAR(36) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_parent_id (parent_id),
    INDEX idx_user_parent (user_id, parent_id),
    FOREIGN KEY (user_id) REFERENCES user(id),
    FOREIGN KEY (parent_id) REFERENCES folder(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Saved paragraph table
CREATE TABLE IF NOT EXISTS saved_paragraph (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    source_url VARCHAR(1024) NOT NULL,
    name VARCHAR(50) NULL,
    content TEXT NOT NULL,
    folder_id CHAR(36) NULL,
    user_id CHAR(36) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_folder_id (folder_id),
    INDEX idx_user_folder_created (user_id, folder_id, created_at),
    FOREIGN KEY (user_id) REFERENCES user(id),
    FOREIGN KEY (folder_id) REFERENCES folder(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Saved page table
CREATE TABLE IF NOT EXISTS saved_page (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    url VARCHAR(1024) NOT NULL,
    name VARCHAR(50) NULL,
    folder_id CHAR(36) NULL,
    user_id CHAR(36) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_folder_id (folder_id),
    INDEX idx_user_folder_created (user_id, folder_id, created_at),
    FOREIGN KEY (user_id) REFERENCES user(id),
    FOREIGN KEY (folder_id) REFERENCES folder(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- File upload table
CREATE TABLE IF NOT EXISTS file_upload (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    file_name VARCHAR(50) NOT NULL,
    entity_type ENUM('ISSUE') NOT NULL,
    entity_id CHAR(36) NOT NULL,
    vendor_type ENUM('CLOUDINARY', 'UPLOADCARE', 'FREEIMAGE'),
    file_url VARCHAR(2044),
    metadata JSON,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_entity_id (entity_id),
    INDEX idx_entity_type (entity_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Issue table
CREATE TABLE IF NOT EXISTS issue (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    ticket_id VARCHAR(14) NOT NULL UNIQUE,
    type ENUM('GLITCH', 'SUBSCRIPTION', 'AUTHENTICATION', 'FEATURE_REQUEST', 'OTHERS') NOT NULL,
    heading VARCHAR(100) NULL,
    description TEXT NOT NULL,
    webpage_url VARCHAR(1024),
    status ENUM('OPEN', 'WORK_IN_PROGRESS', 'DISCARDED', 'RESOLVED') NOT NULL,
    created_by CHAR(36) NOT NULL,
    closed_by CHAR(36) NULL,
    closed_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_created_by (created_by),
    INDEX idx_status (status),
    INDEX idx_ticket_id (ticket_id),
    INDEX idx_created_at (created_at),
    FOREIGN KEY (created_by) REFERENCES user(id),
    FOREIGN KEY (closed_by) REFERENCES user(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Comments table
CREATE TABLE IF NOT EXISTS comment (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    content VARCHAR(1024) NOT NULL,
    entity_type ENUM('ISSUE') NOT NULL,
    entity_id CHAR(36) NOT NULL,
    parent_comment_id CHAR(36) NULL,
    visibility ENUM('PUBLIC', 'INTERNAL') NOT NULL,
    created_by CHAR(36) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_entity (entity_type, entity_id),
    INDEX idx_parent_comment (parent_comment_id),
    INDEX idx_created_by (created_by),
    FOREIGN KEY (parent_comment_id) REFERENCES comment(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES user(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

