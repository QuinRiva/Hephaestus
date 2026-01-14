#!/usr/bin/env python3
"""Add workflow branch isolation and final merge review columns to workflows table."""

import sys
from pathlib import Path

# Add parent directory to path (same pattern as init_db.py)
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text
from src.core.simple_config import get_config


def add_columns():
    """Add the new workflow branch and merge review columns."""
    config = get_config()
    engine = create_engine(f'sqlite:///{config.database_path}')

    # List of columns to add with their types and defaults
    columns_to_add = [
        ("workflow_branch_name", "VARCHAR", None),
        ("workflow_branch_created", "BOOLEAN", "0"),
        ("final_merge_status", "VARCHAR", "'not_applicable'"),
        ("final_merge_reviewed_at", "DATETIME", None),
        ("final_merge_reviewed_by", "VARCHAR", None),
        ("final_merge_commit_sha", "VARCHAR", None),
    ]

    with engine.connect() as conn:
        # Check which columns already exist
        result = conn.execute(text("PRAGMA table_info(workflows)"))
        existing_columns = {row[1] for row in result.fetchall()}

        for col_name, col_type, default_val in columns_to_add:
            if col_name in existing_columns:
                print(f"  ⏭️  Column '{col_name}' already exists, skipping")
                continue

            if default_val is not None:
                sql = f"ALTER TABLE workflows ADD COLUMN {col_name} {col_type} DEFAULT {default_val}"
            else:
                sql = f"ALTER TABLE workflows ADD COLUMN {col_name} {col_type}"

            conn.execute(text(sql))
            print(f"  ✅ Added column '{col_name}'")

        conn.commit()

    print(f"\n✅ Migration complete for {config.database_path}")
    print("   Added workflow branch isolation columns:")
    print("   - workflow_branch_name: Name of the workflow's dedicated branch")
    print("   - workflow_branch_created: Whether the branch has been created")
    print("   Added final merge review columns:")
    print("   - final_merge_status: Review status (not_applicable, pending_review, approved, merged, rejected)")
    print("   - final_merge_reviewed_at: When review decision was made")
    print("   - final_merge_reviewed_by: Who made the decision")
    print("   - final_merge_commit_sha: The merge commit SHA after final merge to main")


if __name__ == "__main__":
    add_columns()
