-- Migration 002: create highlight_colour table
CREATE TABLE IF NOT EXISTS highlight_colour (
    id          CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    hexcode     VARCHAR(7) NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Migration 002: seed 7 gentle pastel highlight colours
INSERT INTO highlight_colour (hexcode) VALUES
    ('#FFF9C4'),  -- Lemon Yellow
    ('#B5EAD7'),  -- Mint Green
    ('#FFDAC1'),  -- Peach
    ('#D4C5F9'),  -- Lavender
    ('#C9E8F5'),  -- Sky Blue
    ('#FFB7B2'),  -- Blush Pink
    ('#E2F0CB');  -- Lime

-- Migration 002: create pdf_highlight table
CREATE TABLE IF NOT EXISTS pdf_highlight (
    id                   CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    pdf_id               CHAR(36) NOT NULL,
    user_id              CHAR(36) NOT NULL,
    highlight_colour_id  CHAR(36) NOT NULL,
    start_text           VARCHAR(15) NOT NULL,
    end_text             VARCHAR(15) NOT NULL,
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
