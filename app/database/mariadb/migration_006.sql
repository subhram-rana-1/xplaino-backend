-- Migration 012: Create shared_user table
CREATE TABLE IF NOT EXISTS shared_user (
    id                                CHAR(36)     PRIMARY KEY DEFAULT (UUID()),
    shared_by_unauthenticated_user_id CHAR(36)     NULL,
    shared_by_user_email              VARCHAR(256) NULL,
    shared_to_email                   VARCHAR(256) NOT NULL,
    created_at                        TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_unauth_sharer (shared_by_unauthenticated_user_id, shared_to_email),
    UNIQUE KEY uq_auth_sharer   (shared_by_user_email, shared_to_email),
    INDEX idx_unauth_sharer     (shared_by_unauthenticated_user_id),
    INDEX idx_auth_sharer       (shared_by_user_email),
    FOREIGN KEY (shared_by_unauthenticated_user_id)
        REFERENCES unauthenticated_user_api_usage(user_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
