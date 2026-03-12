-- Migration 011: Create pdf_content_preprocess table
CREATE TABLE IF NOT EXISTS pdf_content_preprocess (
    id            CHAR(36)    PRIMARY KEY DEFAULT (UUID()),
    pdf_id        CHAR(36)    NOT NULL,
    status        ENUM('PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED') NOT NULL DEFAULT 'PENDING',
    error_message TEXT        NULL,
    created_at    TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_pdf_id (pdf_id),
    INDEX idx_status (status),
    FOREIGN KEY (pdf_id) REFERENCES pdf(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Migration 011: Create pdf_chat_session table
CREATE TABLE IF NOT EXISTS pdf_chat_session (
    id                         CHAR(36)    PRIMARY KEY DEFAULT (UUID()),
    name                       VARCHAR(100) NOT NULL DEFAULT 'Untitled',
    pdf_content_preprocess_id  CHAR(36)    NOT NULL,
    user_id                    CHAR(36)    NULL,
    unauthenticated_user_id    CHAR(36)    NULL,
    created_at                 TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                 TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_preprocess_id  (pdf_content_preprocess_id),
    INDEX idx_user_id        (user_id),
    INDEX idx_unauth_user_id (unauthenticated_user_id),
    FOREIGN KEY (pdf_content_preprocess_id) REFERENCES pdf_content_preprocess(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id)                   REFERENCES user(id) ON DELETE CASCADE,
    FOREIGN KEY (unauthenticated_user_id)   REFERENCES unauthenticated_user_api_usage(user_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Migration 011: Create pdf_chat table
CREATE TABLE IF NOT EXISTS pdf_chat (
    id                  CHAR(36)               PRIMARY KEY DEFAULT (UUID()),
    pdf_chat_session_id CHAR(36)               NOT NULL,
    who                 ENUM('USER', 'SYSTEM') NOT NULL,
    chat                TEXT                   NOT NULL,
    citations           JSON                   NULL,
    created_at          TIMESTAMP              NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_session_id      (pdf_chat_session_id),
    INDEX idx_session_created (pdf_chat_session_id, created_at),
    FOREIGN KEY (pdf_chat_session_id) REFERENCES pdf_chat_session(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
