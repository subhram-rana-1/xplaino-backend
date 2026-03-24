-- Migration 007: Add metadata column and drop user_feedback column from extension_uninstallation_user_feedback
ALTER TABLE extension_uninstallation_user_feedback
    ADD COLUMN metadata JSON NULL AFTER user_feedback;

ALTER TABLE extension_uninstallation_user_feedback
    DROP COLUMN user_feedback;

-- Migration 007: Add pdf_note_comment table
CREATE TABLE IF NOT EXISTS pdf_note_comment (
    id          CHAR(36)       PRIMARY KEY DEFAULT (UUID()),
    pdf_note_id CHAR(36)       NOT NULL,
    user_id     CHAR(36)       NULL,
    content     VARCHAR(1024)  NOT NULL,
    created_at  TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_pdf_note_id (pdf_note_id),
    INDEX idx_user_id     (user_id),
    FOREIGN KEY (pdf_note_id) REFERENCES pdf_note(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id)     REFERENCES user(id)     ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Migration 007: Add web_highlight table (browser extension text highlights)
CREATE TABLE IF NOT EXISTS web_highlight (
    id             CHAR(36)    PRIMARY KEY DEFAULT (UUID()),
    user_id        CHAR(36)    NOT NULL,
    page_url       TEXT        NOT NULL,
    page_url_hash  CHAR(64)    NOT NULL,
    selected_text  TEXT        NOT NULL,
    anchor         JSON        NOT NULL,
    color          VARCHAR(20) NULL,
    note           TEXT        NULL,
    created_at     TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user_url_hash (user_id, page_url_hash),
    INDEX idx_user_id       (user_id),
    FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Migration 007: Add web_note table (browser extension notes on text selections)
CREATE TABLE IF NOT EXISTS web_note (
    id             CHAR(36)  PRIMARY KEY DEFAULT (UUID()),
    user_id        CHAR(36)  NOT NULL,
    page_url       TEXT      NOT NULL,
    page_url_hash  CHAR(64)  NOT NULL,
    selected_text  TEXT      NOT NULL,
    anchor         JSON      NOT NULL,
    content        TEXT      NOT NULL,
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user_url_hash (user_id, page_url_hash),
    INDEX idx_user_id       (user_id),
    FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
