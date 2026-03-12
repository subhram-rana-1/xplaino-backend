-- Insert 3 folders into folder table
INSERT INTO folder (id, name, parent_id, user_id) VALUES
('cb64d4a7-cf86-41c9-8723-a5623c1f6cb5', 'My Paragraphs', NULL, '1a4cee4d-f259-4161-af1c-ef2046a2fe41'),
('ce71ae15-0da7-462b-b949-bd829c224e93', 'Study Notes', NULL, '1a4cee4d-f259-4161-af1c-ef2046a2fe41'),
('eaf434e5-a2a2-468a-b8a8-a0ec8d5e084c', 'Important Paragraphs', 'cb64d4a7-cf86-41c9-8723-a5623c1f6cb5', '1a4cee4d-f259-4161-af1c-ef2046a2fe41');

-- 3 records for folder_id: cb64d4a7-cf86-41c9-8723-a5623c1f6cb5
INSERT INTO saved_paragraph (id, source_url, name, content, folder_id, user_id) VALUES
(UUID(), 'https://example.com/article1', 'Introduction to Machine Learning', 'Machine learning is a subset of artificial intelligence that enables systems to learn and improve from experience without being explicitly programmed. It focuses on the development of computer programs that can access data and use it to learn for themselves.', 'cb64d4a7-cf86-41c9-8723-a5623c1f6cb5', '1a4cee4d-f259-4161-af1c-ef2046a2fe41'),
(UUID(), 'https://example.com/article2', 'Deep Learning Fundamentals', 'Deep learning is a machine learning technique that teaches computers to do what comes naturally to humans: learn by example. Deep learning is a key technology behind driverless cars, enabling them to recognize a stop sign or to distinguish a pedestrian from a lamppost.', 'cb64d4a7-cf86-41c9-8723-a5623c1f6cb5', '1a4cee4d-f259-4161-af1c-ef2046a2fe41'),
(UUID(), 'https://example.com/article3', 'Neural Networks Explained', 'Neural networks are computing systems inspired by biological neural networks. They consist of interconnected nodes (neurons) that process information and can learn patterns from data through a process called training.', 'cb64d4a7-cf86-41c9-8723-a5623c1f6cb5', '1a4cee4d-f259-4161-af1c-ef2046a2fe41');

-- 3 records for folder_id: ce71ae15-0da7-462b-b949-bd829c224e93
INSERT INTO saved_paragraph (id, source_url, name, content, folder_id, user_id) VALUES
(UUID(), 'https://example.com/web1', 'Web Development Basics', 'Web development is the work involved in developing a website for the Internet or an intranet. Web development can range from developing a simple single static page of plain text to complex web applications, electronic businesses, and social network services.', 'ce71ae15-0da7-462b-b949-bd829c224e93', '1a4cee4d-f259-4161-af1c-ef2046a2fe41'),
(UUID(), 'https://example.com/web2', 'RESTful API Design', 'REST (Representational State Transfer) is an architectural style for designing networked applications. A RESTful API uses HTTP requests to GET, PUT, POST, and DELETE data, following REST principles for building web services.', 'ce71ae15-0da7-462b-b949-bd829c224e93', '1a4cee4d-f259-4161-af1c-ef2046a2fe41'),
(UUID(), 'https://example.com/web3', 'Database Design Principles', 'Database design is the process of producing a detailed data model of a database. This data model contains all the needed logical and physical design choices and physical storage parameters needed to generate a design in a data definition language.', 'ce71ae15-0da7-462b-b949-bd829c224e93', '1a4cee4d-f259-4161-af1c-ef2046a2fe41');

-- 3 records for folder_id: eaf434e5-a2a2-468a-b8a8-a0ec8d5e084c
INSERT INTO saved_paragraph (id, source_url, name, content, folder_id, user_id) VALUES
(UUID(), 'https://example.com/tech1', 'Cloud Computing Overview', 'Cloud computing is the delivery of computing services including servers, storage, databases, networking, software, analytics, and intelligence over the Internet to offer faster innovation, flexible resources, and economies of scale.', 'eaf434e5-a2a2-468a-b8a8-a0ec8d5e084c', '1a4cee4d-f259-4161-af1c-ef2046a2fe41'),
(UUID(), 'https://example.com/tech2', 'Containerization with Docker', 'Docker is a platform for developing, shipping, and running applications using containerization. Containers allow a developer to package up an application with all of the parts it needs, such as libraries and other dependencies, and ship it all out as one package.', 'eaf434e5-a2a2-468a-b8a8-a0ec8d5e084c', '1a4cee4d-f259-4161-af1c-ef2046a2fe41'),
(UUID(), 'https://example.com/tech3', 'Microservices Architecture', 'Microservices architecture is a method of developing software systems that tries to focus on building single-function modules with well-defined interfaces and operations. This approach allows for better scalability and maintainability of large applications.', 'eaf434e5-a2a2-468a-b8a8-a0ec8d5e084c', '1a4cee4d-f259-4161-af1c-ef2046a2fe41');

-- 3 records with folder_id: NULL
INSERT INTO saved_paragraph (id, source_url, name, content, folder_id, user_id) VALUES
(UUID(), 'https://example.com/misc1', 'Programming Best Practices', 'Writing clean, maintainable code is essential for long-term project success. This includes following coding standards, writing meaningful comments, using version control effectively, and writing comprehensive tests for your code.', NULL, '1a4cee4d-f259-4161-af1c-ef2046a2fe41'),
(UUID(), 'https://example.com/misc2', 'Version Control with Git', 'Git is a distributed version control system that allows multiple developers to work on the same project simultaneously. It tracks changes in source code during software development and helps coordinate work among programmers.', NULL, '1a4cee4d-f259-4161-af1c-ef2046a2fe41'),
(UUID(), 'https://example.com/misc3', 'Agile Development Methodology', 'Agile software development is an iterative approach to software development that emphasizes flexibility, collaboration, and customer feedback. It breaks down projects into small increments that minimize the amount of up-front planning and design.', NULL, '1a4cee4d-f259-4161-af1c-ef2046a2fe41');


-- Insert 10 records into saved_word table
-- Note: Replace 'YOUR_USER_ID_HERE' with an actual user_id from the user table

INSERT INTO saved_word (id, word, source_url, contextual_meaning, user_id) VALUES
(UUID(), 'serendipity', 'https://example.com/article1', 'The occurrence and development of events by chance in a happy or beneficial way', '1a4cee4d-f259-4161-af1c-ef2046a2fe41'),
(UUID(), 'ephemeral', 'https://example.com/article2', 'Lasting for a very short time; transient', '1a4cee4d-f259-4161-af1c-ef2046a2fe41'),
(UUID(), 'eloquent', 'https://example.com/article3', 'Fluent or persuasive in speaking or writing', '1a4cee4d-f259-4161-af1c-ef2046a2fe41'),
(UUID(), 'resilient', 'https://example.com/article4', 'Able to withstand or recover quickly from difficult conditions', '1a4cee4d-f259-4161-af1c-ef2046a2fe41'),
(UUID(), 'ubiquitous', 'https://example.com/article5', 'Present, appearing, or found everywhere', '1a4cee4d-f259-4161-af1c-ef2046a2fe41'),
(UUID(), 'meticulous', 'https://example.com/article6', 'Showing great attention to detail; very careful and precise', '1a4cee4d-f259-4161-af1c-ef2046a2fe41'),
(UUID(), 'pragmatic', 'https://example.com/article7', 'Dealing with things in a practical and sensible way', '1a4cee4d-f259-4161-af1c-ef2046a2fe41'),
(UUID(), 'ambiguous', 'https://example.com/article8', 'Having more than one possible meaning; unclear', '1a4cee4d-f259-4161-af1c-ef2046a2fe41'),
(UUID(), 'diligent', 'https://example.com/article9', 'Having or showing care and conscientiousness in work or duties', '1a4cee4d-f259-4161-af1c-ef2046a2fe41'),
(UUID(), 'profound', 'https://example.com/article10', 'Having or showing great knowledge or insight; very deep', '1a4cee4d-f259-4161-af1c-ef2046a2fe41');


-- Insert 3 folders into folder table
INSERT INTO folder (id, name, parent_id, user_id) VALUES
('a1b2c3d4-e5f6-4789-0123-456789abcdef', 'Bookmarked Pages', NULL, '1a4cee4d-f259-4161-af1c-ef2046a2fe41'),
('b2c3d4e5-f6a7-4890-1234-567890bcdefg', 'Research Articles', NULL, '1a4cee4d-f259-4161-af1c-ef2046a2fe41'),
('c3d4e5f6-a7b8-4901-2345-678901cdefgh', 'Important Links', 'a1b2c3d4-e5f6-4789-0123-456789abcdef', '1a4cee4d-f259-4161-af1c-ef2046a2fe41');

-- 3 records for folder_id: a1b2c3d4-e5f6-4789-0123-456789abcdef
INSERT INTO saved_link (id, url, name, type, summary, metadata, folder_id, user_id) VALUES
(UUID(), 'https://github.com/facebook/react', 'React - JavaScript Library', 'WEBPAGE', NULL, NULL, 'a1b2c3d4-e5f6-4789-0123-456789abcdef', '1a4cee4d-f259-4161-af1c-ef2046a2fe41'),
(UUID(), 'https://www.python.org/', 'Python Programming Language', 'WEBPAGE', NULL, NULL, 'a1b2c3d4-e5f6-4789-0123-456789abcdef', '1a4cee4d-f259-4161-af1c-ef2046a2fe41'),
(UUID(), 'https://nodejs.org/', 'Node.js Runtime', 'WEBPAGE', NULL, NULL, 'a1b2c3d4-e5f6-4789-0123-456789abcdef', '1a4cee4d-f259-4161-af1c-ef2046a2fe41');

-- 3 records for folder_id: b2c3d4e5-f6a7-4890-1234-567890bcdefg
INSERT INTO saved_link (id, url, name, type, summary, metadata, folder_id, user_id) VALUES
(UUID(), 'https://arxiv.org/', 'arXiv - Research Papers', 'WEBPAGE', NULL, NULL, 'b2c3d4e5-f6a7-4890-1234-567890bcdefg', '1a4cee4d-f259-4161-af1c-ef2046a2fe41'),
(UUID(), 'https://www.nature.com/', 'Nature - Scientific Journal', 'WEBPAGE', NULL, NULL, 'b2c3d4e5-f6a7-4890-1234-567890bcdefg', '1a4cee4d-f259-4161-af1c-ef2046a2fe41'),
(UUID(), 'https://scholar.google.com/', 'Google Scholar', 'WEBPAGE', NULL, NULL, 'b2c3d4e5-f6a7-4890-1234-567890bcdefg', '1a4cee4d-f259-4161-af1c-ef2046a2fe41');

-- 2 records for folder_id: c3d4e5f6-a7b8-4901-2345-678901cdefgh
INSERT INTO saved_link (id, url, name, type, summary, metadata, folder_id, user_id) VALUES
(UUID(), 'https://stackoverflow.com/', 'Stack Overflow - Q&A', 'WEBPAGE', NULL, NULL, 'c3d4e5f6-a7b8-4901-2345-678901cdefgh', '1a4cee4d-f259-4161-af1c-ef2046a2fe41'),
(UUID(), 'https://developer.mozilla.org/', 'MDN Web Docs', 'WEBPAGE', NULL, NULL, 'c3d4e5f6-a7b8-4901-2345-678901cdefgh', '1a4cee4d-f259-4161-af1c-ef2046a2fe41');

-- 2 records with folder_id: NULL
INSERT INTO saved_link (id, url, name, type, summary, metadata, folder_id, user_id) VALUES
(UUID(), 'https://www.wikipedia.org/', 'Wikipedia', 'WEBPAGE', NULL, NULL, NULL, '1a4cee4d-f259-4161-af1c-ef2046a2fe41'),
(UUID(), 'https://www.reddit.com/', 'Reddit', 'REDDIT', NULL, NULL, NULL, '1a4cee4d-f259-4161-af1c-ef2046a2fe41');
