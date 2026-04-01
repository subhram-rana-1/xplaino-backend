-- Migration 008: Add user_feedback table
CREATE TABLE IF NOT EXISTS user_feedback (
    id         CHAR(36)                             PRIMARY KEY DEFAULT (UUID()),
    user_id    CHAR(36)                             NOT NULL,
    verdict    ENUM('UNHAPPY', 'NEUTRAL', 'HAPPY')  NOT NULL,
    metadata   JSON                                 NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_verdict (verdict),
    FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
