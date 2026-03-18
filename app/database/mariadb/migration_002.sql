-- Migration 002: create highlight_colour table
CREATE TABLE IF NOT EXISTS highlight_colour (
    id          CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    hexcode     VARCHAR(7) NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Migration 002: seed 7 highlight colours
INSERT INTO highlight_colour (hexcode) VALUES
    ('#FFE082'),  -- Lemon Yellow
    ('#80CBC4'),  -- Mint Green
    ('#FFAB91'),  -- Peach
    ('#B39DDB'),  -- Lavender
    ('#90CAF9'),  -- Sky Blue
    ('#EF9A9A'),  -- Blush Pink
    ('#C5E1A5');  -- Lime

-- Migration 002: create pdf_highlight table
CREATE TABLE IF NOT EXISTS pdf_highlight (
    id                   CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    pdf_id               CHAR(36) NOT NULL,
    user_id              CHAR(36) NOT NULL,
    highlight_colour_id  CHAR(36) NOT NULL,
    start_text           VARCHAR(50) NOT NULL,
    end_text             VARCHAR(50) NOT NULL,
    created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_pdf_id (pdf_id),
    INDEX idx_user_id (user_id),
    FOREIGN KEY (pdf_id)              REFERENCES pdf(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id)             REFERENCES user(id) ON DELETE CASCADE,
    FOREIGN KEY (highlight_colour_id) REFERENCES highlight_colour(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Migration 003: drop type column from folder table
ALTER TABLE folder DROP COLUMN type;

-- Migration 004: create pdf_note table
CREATE TABLE IF NOT EXISTS pdf_note (
    id          CHAR(36)      PRIMARY KEY DEFAULT (UUID()),
    pdf_id      CHAR(36)      NOT NULL,
    user_id     CHAR(36)      NOT NULL,
    start_text  VARCHAR(50)   NOT NULL,
    end_text    VARCHAR(50)   NOT NULL,
    content     VARCHAR(1024) NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_pdf_id  (pdf_id),
    INDEX idx_user_id (user_id),
    FOREIGN KEY (pdf_id)  REFERENCES pdf(id)  ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Migration 005: widen start_text / end_text on pdf_highlight and pdf_note
ALTER TABLE pdf_highlight
    MODIFY COLUMN start_text VARCHAR(50) NOT NULL,
    MODIFY COLUMN end_text   VARCHAR(50) NOT NULL;

ALTER TABLE pdf_note
    MODIFY COLUMN start_text VARCHAR(50) NOT NULL,
    MODIFY COLUMN end_text   VARCHAR(50) NOT NULL;

-- Migration 006: create folder_share table
CREATE TABLE IF NOT EXISTS folder_share (
    id              CHAR(36)     PRIMARY KEY DEFAULT (UUID()),
    folder_id       CHAR(36)     NOT NULL,
    shared_to_email VARCHAR(256) NOT NULL,
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_folder_shared_to_email (folder_id, shared_to_email),
    INDEX idx_folder_id       (folder_id),
    INDEX idx_shared_to_email (shared_to_email),
    FOREIGN KEY (folder_id) REFERENCES folder(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Migration 006: create pdf_share table
CREATE TABLE IF NOT EXISTS pdf_share (
    id              CHAR(36)     PRIMARY KEY DEFAULT (UUID()),
    pdf_id          CHAR(36)     NOT NULL,
    shared_to_email VARCHAR(256) NOT NULL,
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_pdf_shared_to_email (pdf_id, shared_to_email),
    INDEX idx_pdf_id          (pdf_id),
    INDEX idx_shared_to_email (shared_to_email),
    FOREIGN KEY (pdf_id) REFERENCES pdf(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Migration 007: Add access_level to pdf table
ALTER TABLE pdf
    ADD COLUMN access_level ENUM('PRIVATE', 'PUBLIC') NOT NULL DEFAULT 'PRIVATE';

-- Migration 008: Add parent_id to pdf table (self-referential FK for copied PDFs)
ALTER TABLE pdf
    ADD COLUMN parent_id CHAR(36) NULL,
    ADD INDEX idx_parent_id (parent_id),
    ADD CONSTRAINT fk_pdf_parent_id FOREIGN KEY (parent_id) REFERENCES pdf(id) ON DELETE SET NULL;
