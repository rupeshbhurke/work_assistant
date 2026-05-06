import pytest
from pathlib import Path
from workassistant.tools.project_tools import (
    scan_projects,
    list_projects,
    add_project_location,
)

@pytest.mark.asyncio
async def test_add_project_location():
    """Test adding a project location."""
    result = await add_project_location("/tmp/test_projects", is_primary=True)
    
    if "error" in result:
        assert "does not exist" in result["error"]
    else:
        assert result["success"] is True

@pytest.mark.asyncio
async def test_list_projects():
    """Test listing projects."""
    result = await list_projects()
    assert isinstance(result, list)
