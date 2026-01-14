"""Service for exporting incident memories to markdown files."""

import os
import re
import logging
from datetime import datetime
from typing import List, Dict, Any

from src.core.database import get_db, Memory, Agent

logger = logging.getLogger(__name__)


class IncidentExportService:
    """Exports incident memories to markdown format at workflow end."""

    @staticmethod
    def export_all(workflow_id: str, output_dir: str = "agent_incidents") -> Dict[str, Any]:
        """Export all incidents for a workflow to markdown files.

        Args:
            workflow_id: The workflow to export incidents for
            output_dir: Directory to write incident files (default: agent_incidents/)

        Returns:
            Dict with export statistics
        """
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(os.path.join(output_dir, "incidents"), exist_ok=True)

        incidents = IncidentExportService._query_incidents(workflow_id)

        timeline_path = IncidentExportService._export_timeline(incidents, output_dir)
        incident_files = IncidentExportService._export_incident_reports(incidents, output_dir)
        readme_path = IncidentExportService._export_index(incidents, incident_files, output_dir)

        return {
            "total_incidents": len(incidents),
            "timeline_path": timeline_path,
            "incident_files": incident_files,
            "readme_path": readme_path,
        }

    @staticmethod
    def _query_incidents(workflow_id: str) -> List[Dict[str, Any]]:
        """Query all memories with 'incident' tag for this workflow."""
        with get_db() as session:
            agents = session.query(Agent).filter(
                Agent.workflow_id == workflow_id
            ).all()
            agent_ids = [a.id for a in agents]

            if not agent_ids:
                return []

            memories = session.query(Memory).filter(
                Memory.agent_id.in_(agent_ids)
            ).order_by(Memory.created_at).all()

            incidents = []
            for mem in memories:
                tags = mem.tags or []
                if "incident" in tags:
                    incidents.append({
                        "id": mem.id,
                        "agent_id": mem.agent_id,
                        "content": mem.content,
                        "memory_type": mem.memory_type,
                        "tags": tags,
                        "related_files": mem.related_files or [],
                        "created_at": mem.created_at,
                    })

            return incidents

    @staticmethod
    def _parse_incident_content(content: str) -> Dict[str, str]:
        """Parse structured incident content into components."""
        result = {
            "title": "Unknown Incident",
            "symptom": "",
            "attempted": "",
            "status": "OPEN",
            "verify": "",
        }

        if content.startswith("INCIDENT:"):
            parts = content.split("|")
            for part in parts:
                part = part.strip()
                if part.startswith("INCIDENT:"):
                    result["title"] = part.replace("INCIDENT:", "").strip()
                elif part.startswith("symptom:"):
                    result["symptom"] = part.replace("symptom:", "").strip()
                elif part.startswith("attempted:"):
                    result["attempted"] = part.replace("attempted:", "").strip()
                elif part.startswith("status:"):
                    result["status"] = part.replace("status:", "").strip()
                elif part.startswith("verify:"):
                    result["verify"] = part.replace("verify:", "").strip()
        else:
            result["title"] = content[:50] + "..." if len(content) > 50 else content
            result["symptom"] = content

        return result

    @staticmethod
    def _generate_slug(title: str) -> str:
        """Generate kebab-case slug from title."""
        slug = title.lower()
        slug = re.sub(r'[^a-z0-9\s-]', '', slug)
        slug = re.sub(r'[\s_]+', '-', slug)
        slug = re.sub(r'-+', '-', slug)
        slug = slug.strip('-')
        return slug[:40]

    @staticmethod
    def _get_next_incident_id(output_dir: str) -> int:
        """Scan existing INC-*.md files and return next ID."""
        incidents_dir = os.path.join(output_dir, "incidents")
        if not os.path.exists(incidents_dir):
            return 1

        max_id = 0
        for filename in os.listdir(incidents_dir):
            if filename.startswith("INC-") and filename.endswith(".md"):
                try:
                    id_str = filename.split("-")[1]
                    id_num = int(id_str)
                    max_id = max(max_id, id_num)
                except (IndexError, ValueError):
                    continue

        return max_id + 1

    @staticmethod
    def _export_timeline(incidents: List[Dict], output_dir: str) -> str:
        """Generate timeline.md with one line per incident."""
        timeline_path = os.path.join(output_dir, "timeline.md")

        with open(timeline_path, "w") as f:
            f.write("# Incident Timeline\n\n")
            f.write("| Timestamp | Title | Status | Agent | Tags |\n")
            f.write("|-----------|-------|--------|-------|------|\n")

            for inc in incidents:
                parsed = IncidentExportService._parse_incident_content(inc["content"])
                timestamp = inc["created_at"].strftime("%Y-%m-%d %H:%M UTC")
                agent_short = inc["agent_id"][:8]
                tags = ", ".join(t for t in inc["tags"] if t != "incident")

                f.write(f"| {timestamp} | {parsed['title'][:40]} | {parsed['status']} | {agent_short} | {tags} |\n")

        return timeline_path

    @staticmethod
    def _export_incident_reports(incidents: List[Dict], output_dir: str) -> List[str]:
        """Generate INC-NNNN-slug.md for each incident."""
        incident_files = []
        next_id = IncidentExportService._get_next_incident_id(output_dir)

        for i, inc in enumerate(incidents):
            parsed = IncidentExportService._parse_incident_content(inc["content"])
            slug = IncidentExportService._generate_slug(parsed["title"])
            inc_id = f"INC-{next_id + i:04d}"
            filename = f"{inc_id}-{slug}.md"
            filepath = os.path.join(output_dir, "incidents", filename)

            classifications = [t for t in inc["tags"] if t != "incident"]
            classification = classifications[0] if classifications else "unknown"

            with open(filepath, "w") as f:
                f.write(f"""---
id: {inc_id}
status: {parsed['status']}
timestamp_opened: {inc['created_at'].isoformat()}
severity: MEDIUM
classification: {classification}
tags: {inc['tags']}
agent_id: {inc['agent_id']}
---

# Summary

{parsed['title']}

# Symptoms

{parsed['symptom']}

# Resolution Attempted

{parsed['attempted']}

# Verification

{parsed['verify']}

# Related Files

{chr(10).join('- ' + f for f in inc['related_files']) if inc['related_files'] else 'None recorded'}

# Raw Memory Content

```
{inc['content']}
```
""")
            incident_files.append(filename)

        return incident_files

    @staticmethod
    def _export_index(incidents: List[Dict], incident_files: List[str], output_dir: str) -> str:
        """Generate README.md with index and statistics."""
        readme_path = os.path.join(output_dir, "README.md")

        by_status: Dict[str, int] = {}
        by_classification: Dict[str, int] = {}
        for inc in incidents:
            parsed = IncidentExportService._parse_incident_content(inc["content"])
            status = parsed["status"]
            by_status[status] = by_status.get(status, 0) + 1

            classifications = [t for t in inc["tags"] if t != "incident"]
            for c in classifications:
                by_classification[c] = by_classification.get(c, 0) + 1

        with open(readme_path, "w") as f:
            f.write("# Agent Incidents\n\n")
            f.write(f"**Total Incidents**: {len(incidents)}\n\n")

            f.write("## Statistics\n\n")
            f.write("### By Status\n")
            for status, count in sorted(by_status.items()):
                f.write(f"- {status}: {count}\n")

            f.write("\n### By Classification\n")
            for classification, count in sorted(by_classification.items()):
                f.write(f"- {classification}: {count}\n")

            f.write("\n## Incident Index\n\n")
            for filename in incident_files:
                f.write(f"- [incidents/{filename}](incidents/{filename})\n")

            f.write("\n## Timeline\n\n")
            f.write("See [timeline.md](timeline.md) for chronological view.\n")

        return readme_path
