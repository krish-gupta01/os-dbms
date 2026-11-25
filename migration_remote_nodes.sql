-- Safe for MySQL versions that do not support ADD COLUMN IF NOT EXISTS.
-- Run this on an existing dfms_db database before registering remote storage nodes.
USE dfms_db;

DROP PROCEDURE IF EXISTS add_remote_node_columns;
DELIMITER //

CREATE PROCEDURE add_remote_node_columns()
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'storage_nodes'
      AND column_name = 'node_url'
  ) THEN
    ALTER TABLE storage_nodes ADD COLUMN node_url VARCHAR(255) NULL AFTER base_path;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'storage_nodes'
      AND column_name = 'last_heartbeat'
  ) THEN
    ALTER TABLE storage_nodes ADD COLUMN last_heartbeat TIMESTAMP NULL AFTER status;
  END IF;
END //

DELIMITER ;
CALL add_remote_node_columns();
DROP PROCEDURE add_remote_node_columns;