CREATE DATABASE IF NOT EXISTS dfms_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE dfms_db;

CREATE TABLE IF NOT EXISTS users (
  user_id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(80) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  role ENUM('admin','user') NOT NULL DEFAULT 'user',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS storage_nodes (
  node_id INT AUTO_INCREMENT PRIMARY KEY,
  node_name VARCHAR(80) NOT NULL UNIQUE,
  base_path VARCHAR(500) NOT NULL,
  node_url VARCHAR(255) NULL,
  capacity_bytes BIGINT NOT NULL DEFAULT 10737418240,
  used_bytes BIGINT NOT NULL DEFAULT 0,
  status ENUM('ONLINE','OFFLINE','DEGRADED') NOT NULL DEFAULT 'ONLINE',
  last_heartbeat TIMESTAMP NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK (capacity_bytes >= 0),
  CHECK (used_bytes >= 0)
);

CREATE TABLE IF NOT EXISTS files (
  file_id BIGINT AUTO_INCREMENT PRIMARY KEY,
  owner_id INT NOT NULL,
  original_name VARCHAR(255) NOT NULL,
  stored_name VARCHAR(300) NOT NULL,
  size_bytes BIGINT NOT NULL,
  sha256 CHAR(64) NOT NULL,
  content_type VARCHAR(150),
  deleted TINYINT(1) NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (owner_id) REFERENCES users(user_id),
  INDEX idx_files_owner_deleted (owner_id, deleted),
  CHECK (size_bytes >= 0)
);

CREATE TABLE IF NOT EXISTS file_replicas (
  replica_id BIGINT AUTO_INCREMENT PRIMARY KEY,
  file_id BIGINT NOT NULL,
  node_id INT NOT NULL,
  relative_path VARCHAR(600) NOT NULL,
  replica_status ENUM('HEALTHY','MISSING','CORRUPT') NOT NULL DEFAULT 'HEALTHY',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_file_node (file_id, node_id),
  FOREIGN KEY (file_id) REFERENCES files(file_id),
  FOREIGN KEY (node_id) REFERENCES storage_nodes(node_id)
);

CREATE TABLE IF NOT EXISTS file_permissions (
  permission_id BIGINT AUTO_INCREMENT PRIMARY KEY,
  file_id BIGINT NOT NULL,
  user_id INT NOT NULL,
  can_read TINYINT(1) NOT NULL DEFAULT 1,
  can_write TINYINT(1) NOT NULL DEFAULT 0,
  UNIQUE KEY uq_file_user (file_id, user_id),
  FOREIGN KEY (file_id) REFERENCES files(file_id),
  FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS file_requests (
  request_id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  file_id BIGINT NULL,
  operation ENUM('UPLOAD','DOWNLOAD','DELETE','REPAIR') NOT NULL,
  priority INT NOT NULL DEFAULT 5,
  status ENUM('QUEUED','PROCESSING','COMPLETED','FAILED') NOT NULL DEFAULT 'QUEUED',
  details VARCHAR(1000),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  completed_at TIMESTAMP NULL,
  FOREIGN KEY (user_id) REFERENCES users(user_id),
  FOREIGN KEY (file_id) REFERENCES files(file_id),
  INDEX idx_requests_schedule (status, priority, created_at)
);

CREATE TABLE IF NOT EXISTS audit_logs (
  log_id BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NULL,
  action VARCHAR(80) NOT NULL,
  details TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE SET NULL
);


-- Chunk-level distributed storage metadata. Each logical chunk can have multiple replicas.
CREATE TABLE IF NOT EXISTS file_chunks (
  chunk_id BIGINT AUTO_INCREMENT PRIMARY KEY,
  file_id BIGINT NOT NULL,
  chunk_index INT NOT NULL,
  size_bytes BIGINT NOT NULL,
  sha256 CHAR(64) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_file_chunk_index (file_id, chunk_index),
  FOREIGN KEY (file_id) REFERENCES files(file_id),
  CHECK (chunk_index >= 0), CHECK (size_bytes >= 0)
);

CREATE TABLE IF NOT EXISTS chunk_replicas (
  chunk_replica_id BIGINT AUTO_INCREMENT PRIMARY KEY,
  chunk_id BIGINT NOT NULL,
  node_id INT NOT NULL,
  relative_path VARCHAR(600) NOT NULL,
  replica_status ENUM('HEALTHY','MISSING','CORRUPT') NOT NULL DEFAULT 'HEALTHY',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_chunk_node (chunk_id, node_id),
  FOREIGN KEY (chunk_id) REFERENCES file_chunks(chunk_id) ON DELETE CASCADE,
  FOREIGN KEY (node_id) REFERENCES storage_nodes(node_id)
);
