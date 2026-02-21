-- MariaDB Schema for Caten Application
-- This file defines the database tables for user authentication and session management

-- User table
CREATE TABLE IF NOT EXISTS user (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    role ENUM('ADMIN', 'SUPER_ADMIN') NULL,
    settings JSON NOT NULL,
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

-- Unsubscribed user API usage table (for authenticated users without subscription)
CREATE TABLE IF NOT EXISTS unsubscribed_user_api_usage (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    user_id CHAR(36) NOT NULL,
    ip_address VARCHAR(255) NOT NULL,
    api_usage JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_ip_address (ip_address),
    FOREIGN KEY (user_id) REFERENCES user(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Folder table
CREATE TABLE IF NOT EXISTS folder (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    name VARCHAR(50) NOT NULL,
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

-- Saved words table
CREATE TABLE IF NOT EXISTS saved_word (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    word VARCHAR(32) NOT NULL,
    source_url VARCHAR(1024) NOT NULL,
    contextual_meaning VARCHAR(1000) NULL,
    folder_id CHAR(36) NOT NULL,
    user_id CHAR(36) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_folder_id (folder_id),
    INDEX idx_user_created_at (user_id, created_at),
    INDEX idx_user_folder_created (user_id, folder_id, created_at),
    FOREIGN KEY (user_id) REFERENCES user(id),
    FOREIGN KEY (folder_id) REFERENCES folder(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Saved paragraph table
CREATE TABLE IF NOT EXISTS saved_paragraph (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    source_url VARCHAR(1024) NOT NULL,
    name VARCHAR(50) NULL,
    content TEXT NOT NULL,
    folder_id CHAR(36) NOT NULL,
    user_id CHAR(36) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_folder_id (folder_id),
    INDEX idx_user_folder_created (user_id, folder_id, created_at),
    FOREIGN KEY (user_id) REFERENCES user(id),
    FOREIGN KEY (folder_id) REFERENCES folder(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Saved link table
CREATE TABLE IF NOT EXISTS saved_link (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    url VARCHAR(1024) NOT NULL,
    name VARCHAR(100) NULL,
    type ENUM('WEBPAGE', 'YOUTUBE', 'LINKEDIN', 'TWITTER', 'REDDIT', 'FACEBOOK', 'INSTAGRAM') NOT NULL DEFAULT 'WEBPAGE',
    summary TEXT NULL,
    metadata JSON NULL,
    folder_id CHAR(36) NOT NULL,
    user_id CHAR(36) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_folder_id (folder_id),
    INDEX idx_url (url),
    INDEX idx_user_folder_created (user_id, folder_id, created_at),
    UNIQUE KEY uk_url_user_id (url, user_id),
    FOREIGN KEY (user_id) REFERENCES user(id),
    FOREIGN KEY (folder_id) REFERENCES folder(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- File upload table
-- When entity_type = 'PDF', entity_id references pdf(id). When entity_type = 'ISSUE', entity_id references issue(id).
CREATE TABLE IF NOT EXISTS file_upload (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    file_name VARCHAR(50) NOT NULL,
    file_type ENUM('IMAGE', 'PDF') NOT NULL,
    entity_type ENUM('ISSUE', 'PDF') NOT NULL,
    entity_id CHAR(36) NOT NULL,
    s3_key VARCHAR(1024) NOT NULL,
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

-- Pricing table
CREATE TABLE IF NOT EXISTS pricing (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    name VARCHAR(30) NOT NULL,
    activation TIMESTAMP NOT NULL,
    expiry TIMESTAMP NOT NULL,
    status ENUM('ENABLED', 'DISABLED') NOT NULL,
    features JSON NOT NULL,
    currency ENUM('USD') NOT NULL,
    pricing_details JSON NOT NULL,
    description VARCHAR(500) NOT NULL,
    is_highlighted BOOLEAN NULL,
    created_by CHAR(36) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_status (status),
    INDEX idx_activation (activation),
    INDEX idx_expiry (expiry),
    FOREIGN KEY (created_by) REFERENCES user(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Subscription table
CREATE TABLE IF NOT EXISTS subscription (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    pricing_id CHAR(36) NOT NULL,
    user_id CHAR(36) NOT NULL,
    starts_at TIMESTAMP NOT NULL,
    ends_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_pricing_id (pricing_id),
    INDEX idx_user_id (user_id),
    FOREIGN KEY (pricing_id) REFERENCES pricing(id) ON DELETE RESTRICT,
    FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Domain table
CREATE TABLE IF NOT EXISTS domain (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    url VARCHAR(100) NOT NULL,
    status ENUM('ALLOWED', 'BANNED') NOT NULL DEFAULT 'ALLOWED',
    created_by CHAR(36) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_url (url),
    INDEX idx_status (status),
    FOREIGN KEY (created_by) REFERENCES user(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Saved image table
CREATE TABLE IF NOT EXISTS saved_image (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    source_url VARCHAR(1024) NOT NULL,
    image_url VARCHAR(1024) NOT NULL,
    name VARCHAR(100) NULL,
    folder_id CHAR(36) NOT NULL,
    user_id CHAR(36) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_folder_id (folder_id),
    INDEX idx_user_folder_created (user_id, folder_id, created_at),
    FOREIGN KEY (user_id) REFERENCES user(id),
    FOREIGN KEY (folder_id) REFERENCES folder(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- PDF table
CREATE TABLE IF NOT EXISTS pdf (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    file_name VARCHAR(255) NOT NULL,
    created_by CHAR(36) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_created_by (created_by),
    FOREIGN KEY (created_by) REFERENCES user(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Coupon table
CREATE TABLE IF NOT EXISTS coupon (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    code VARCHAR(30) NOT NULL,
    name VARCHAR(100) NOT NULL,
    description VARCHAR(1024) NOT NULL,
    discount FLOAT NOT NULL,
    activation TIMESTAMP NOT NULL,
    expiry TIMESTAMP NOT NULL,
    status ENUM('ENABLED', 'DISABLED') NOT NULL,
    is_highlighted BOOLEAN NOT NULL DEFAULT FALSE,
    created_by CHAR(36) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_status (status),
    INDEX idx_code (code),
    INDEX idx_activation_expiry (activation, expiry),
    INDEX idx_is_highlighted_status (is_highlighted, status),
    FOREIGN KEY (created_by) REFERENCES user(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Pre-launch user table
CREATE TABLE IF NOT EXISTS pre_launch_user (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    email VARCHAR(100) NOT NULL,
    meta_info JSON NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_pre_launch_user_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================
-- PADDLE BILLING INTEGRATION TABLES
-- =====================================================

-- Paddle Customer table (synced from Paddle webhooks)
CREATE TABLE IF NOT EXISTS paddle_customer (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    paddle_customer_id VARCHAR(50) NOT NULL UNIQUE,
    user_id CHAR(36) NULL,
    email VARCHAR(256) NOT NULL,
    name VARCHAR(256) NULL,
    locale VARCHAR(10) NULL,
    marketing_consent BOOLEAN DEFAULT FALSE,
    status ENUM('ACTIVE', 'ARCHIVED') NOT NULL DEFAULT 'ACTIVE',
    custom_data JSON NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_paddle_customer_id (paddle_customer_id),
    INDEX idx_user_id (user_id),
    INDEX idx_email (email),
    FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Paddle Subscription table (synced from Paddle webhooks)
CREATE TABLE IF NOT EXISTS paddle_subscription (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    paddle_subscription_id VARCHAR(50) NOT NULL UNIQUE,
    paddle_customer_id VARCHAR(50) NOT NULL,
    user_id CHAR(36) NULL,
    status ENUM('ACTIVE', 'CANCELED', 'PAST_DUE', 'PAUSED', 'TRIALING') NOT NULL,
    currency_code VARCHAR(3) NOT NULL,
    billing_cycle_interval ENUM('DAY', 'WEEK', 'MONTH', 'YEAR') NOT NULL,
    billing_cycle_frequency INT NOT NULL DEFAULT 1,
    current_billing_period_starts_at TIMESTAMP NULL,
    current_billing_period_ends_at TIMESTAMP NULL,
    next_billed_at TIMESTAMP NULL,
    paused_at TIMESTAMP NULL,
    canceled_at TIMESTAMP NULL,
    cancellation_info JSON NULL,
    scheduled_change JSON NULL,
    items JSON NOT NULL,
    custom_data JSON NULL,
    first_billed_at TIMESTAMP NULL,
    started_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_paddle_subscription_id (paddle_subscription_id),
    INDEX idx_paddle_customer_id (paddle_customer_id),
    INDEX idx_user_id (user_id),
    INDEX idx_status (status),
    INDEX idx_next_billed_at (next_billed_at),
    FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Paddle Transaction table (synced from Paddle webhooks)
CREATE TABLE IF NOT EXISTS paddle_transaction (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    paddle_transaction_id VARCHAR(50) NOT NULL UNIQUE,
    paddle_subscription_id VARCHAR(50) NULL,
    paddle_customer_id VARCHAR(50) NOT NULL,
    user_id CHAR(36) NULL,
    status ENUM('DRAFT', 'READY', 'BILLED', 'PAID', 'COMPLETED', 'CANCELED', 'PAST_DUE') NOT NULL,
    origin ENUM('API', 'SUBSCRIPTION_RECURRING', 'SUBSCRIPTION_PAYMENT_METHOD_CHANGE', 'SUBSCRIPTION_UPDATE', 'WEB') NULL,
    currency_code VARCHAR(3) NOT NULL,
    subtotal VARCHAR(20) NOT NULL,
    tax VARCHAR(20) NOT NULL,
    total VARCHAR(20) NOT NULL,
    grand_total VARCHAR(20) NOT NULL,
    discount_total VARCHAR(20) NULL DEFAULT '0',
    items JSON NOT NULL,
    payments JSON NULL,
    billed_at TIMESTAMP NULL,
    invoice_id VARCHAR(50) NULL,
    invoice_number VARCHAR(50) NULL,
    custom_data JSON NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_paddle_transaction_id (paddle_transaction_id),
    INDEX idx_paddle_subscription_id (paddle_subscription_id),
    INDEX idx_paddle_customer_id (paddle_customer_id),
    INDEX idx_user_id (user_id),
    INDEX idx_status (status),
    INDEX idx_billed_at (billed_at),
    FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Paddle Webhook Event Log table (for idempotency and debugging)
CREATE TABLE IF NOT EXISTS paddle_webhook_event (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    paddle_event_id VARCHAR(50) NOT NULL UNIQUE,
    event_type VARCHAR(50) NOT NULL,
    occurred_at TIMESTAMP NOT NULL,
    payload JSON NOT NULL,
    processing_status ENUM('RECEIVED', 'PROCESSING', 'PROCESSED', 'FAILED') NOT NULL DEFAULT 'RECEIVED',
    processing_error TEXT NULL,
    processed_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_paddle_event_id (paddle_event_id),
    INDEX idx_event_type (event_type),
    INDEX idx_occurred_at (occurred_at),
    INDEX idx_processing_status (processing_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Paddle Adjustment table (refunds, credits, chargebacks)
CREATE TABLE IF NOT EXISTS paddle_adjustment (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    paddle_adjustment_id VARCHAR(50) NOT NULL UNIQUE,
    paddle_transaction_id VARCHAR(50) NOT NULL,
    paddle_customer_id VARCHAR(50) NOT NULL,
    paddle_subscription_id VARCHAR(50) NULL,
    action ENUM('REFUND', 'CREDIT', 'CHARGEBACK', 'CHARGEBACK_REVERSE', 'CHARGEBACK_WARNING') NOT NULL,
    status ENUM('PENDING', 'APPROVED', 'REJECTED') NOT NULL,
    reason VARCHAR(500) NULL,
    currency_code VARCHAR(3) NOT NULL,
    total VARCHAR(20) NOT NULL,
    payout_totals JSON NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_paddle_adjustment_id (paddle_adjustment_id),
    INDEX idx_paddle_transaction_id (paddle_transaction_id),
    INDEX idx_paddle_customer_id (paddle_customer_id),
    INDEX idx_status (status),
    INDEX idx_action (action)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Extension uninstallation user feedback table
CREATE TABLE IF NOT EXISTS extension_uninstallation_user_feedback (
    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    reason ENUM('TOO_EXPENSIVE', 'NOT_USING', 'FOUND_ALTERNATIVE', 'MISSING_FEATURES', 'EXTENSION_NOT_WORKING', 'OTHER') NOT NULL,
    user_feedback TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

