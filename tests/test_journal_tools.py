import pytest
from datetime import datetime
from workassistant.tools.journal_tools import (
    add_journal_entry,
    search_journal,
)

@pytest.mark.asyncio
async def test_add_journal_entry():
    """Test creating a journal entry."""
    result = await add_journal_entry(
        summary="Test entry",
        details="This is a test journal entry",
        tags=["test", "development"],
        entry_type="free-form"
    )
    
    assert result["success"] is True
    assert "entry_id" in result

@pytest.mark.asyncio
async def test_search_journal():
    """Test searching journal entries."""
    result = await search_journal(query="test", limit=10)
    
    assert result["success"] is True
    assert "entries" in result
    assert isinstance(result["entries"], list)
