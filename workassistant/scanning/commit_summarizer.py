import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from workassistant.models.ai_api_call import AIApiCall
from workassistant.config import (
    OPENAI_API_KEY,
    AI_SUMMARY_MODEL,
    AI_MAX_OUTPUT_TOKENS,
    COMMIT_AGE_THRESHOLD_DAYS,
    MAX_FILE_SIZE_BYTES,
    MAX_DIFF_SIZE_BYTES,
    AI_PRICING,
)


class CommitSummaryGenerator:
    """Generates AI summaries from git diffs and tracks API costs."""

    def __init__(self, session: AsyncSession, model: str = AI_SUMMARY_MODEL):
        self.session = session
        self.model = model
        self._client: Optional[AsyncOpenAI] = None

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        return self._client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate_summary(self, diff: str, commit_metadata: dict) -> dict:
        """Generate an AI summary for one commit.

        commit_metadata keys: hash, author, date (ISO string), message
        Returns: {summary, ai_skipped, ai_error, api_call_id}
        """
        # Age gate — skip commits older than threshold
        try:
            commit_date = datetime.fromisoformat(commit_metadata["date"])
            if commit_date.tzinfo is None:
                commit_date = commit_date.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - commit_date).days
        except (KeyError, ValueError):
            age_days = 0

        if age_days > COMMIT_AGE_THRESHOLD_DAYS:
            return {
                "summary": None,
                "ai_skipped": True,
                "ai_error": f"Commit older than {COMMIT_AGE_THRESHOLD_DAYS} days",
                "api_call_id": None,
            }

        filtered_diff = self._filter_diff(diff)
        if not filtered_diff.strip():
            return {
                "summary": None,
                "ai_skipped": True,
                "ai_error": "Empty diff after filtering",
                "api_call_id": None,
            }

        try:
            summary, api_call_id = await self._call_with_retry(filtered_diff, commit_metadata)
            return {"summary": summary, "ai_skipped": False, "ai_error": None, "api_call_id": api_call_id}
        except Exception as exc:
            api_call_id = await self._log_api_call(
                input_tokens=0, output_tokens=0, success=False, error_message=str(exc)
            )
            return {"summary": None, "ai_skipped": False, "ai_error": str(exc), "api_call_id": api_call_id}

    # ------------------------------------------------------------------
    # Diff filtering
    # ------------------------------------------------------------------

    def _filter_diff(self, diff: str) -> str:
        """Strip per-file sections that exceed MAX_FILE_SIZE_BYTES, then
        truncate the overall diff to MAX_DIFF_SIZE_BYTES."""
        sections: list[str] = []
        current: list[str] = []

        for line in diff.splitlines(keepends=True):
            if line.startswith("diff --git"):
                if current:
                    sections.append("".join(current))
                current = [line]
            else:
                current.append(line)
        if current:
            sections.append("".join(current))

        kept: list[str] = []
        for section in sections:
            if len(section.encode()) <= MAX_FILE_SIZE_BYTES:
                kept.append(section)

        result = "".join(kept)
        # Truncate to overall diff size limit
        if len(result.encode()) > MAX_DIFF_SIZE_BYTES:
            result = result.encode()[:MAX_DIFF_SIZE_BYTES].decode(errors="ignore")
            result += "\n... [diff truncated]"
        return result

    # ------------------------------------------------------------------
    # AI call
    # ------------------------------------------------------------------

    async def _call_with_retry(
        self, diff: str, commit_metadata: dict, max_retries: int = 3
    ) -> tuple[str, int]:
        prompt = (
            f"Analyze this git diff and write a concise summary (max 200 words).\n\n"
            f"Commit: {commit_metadata.get('hash', '')[:12]}\n"
            f"Author: {commit_metadata.get('author', 'unknown')}\n"
            f"Date: {commit_metadata.get('date', '')}\n"
            f"Message: {commit_metadata.get('message', '')}\n\n"
            f"Diff:\n{diff}\n\n"
            f"Guidelines:\n"
            f"1. Describe what changed (features, fixes, refactors)\n"
            f"2. Identify affected components/modules\n"
            f"3. Highlight important technical details\n"
            f"4. Mention the author: {commit_metadata.get('author', 'unknown')}\n"
            f"5. Be concise and actionable"
        )

        last_error: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                request_time = datetime.now(timezone.utc)
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=AI_MAX_OUTPUT_TOKENS,
                    temperature=0.3,
                )
                response_time = datetime.now(timezone.utc)
                duration_ms = int((response_time - request_time).total_seconds() * 1000)

                input_tokens = response.usage.prompt_tokens
                output_tokens = response.usage.completion_tokens
                cost = self._calculate_cost(input_tokens, output_tokens)
                summary_text = response.choices[0].message.content or ""

                api_call_id = await self._log_api_call(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=response.usage.total_tokens,
                    cost_usd=cost,
                    request_timestamp=request_time,
                    response_timestamp=response_time,
                    duration_ms=duration_ms,
                    success=True,
                )
                return summary_text.strip(), api_call_id

            except Exception as exc:
                last_error = exc
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)

        raise last_error  # type: ignore[misc]

    def _calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        pricing = AI_PRICING.get(self.model, {"input": 0.01, "output": 0.03})
        return (input_tokens / 1_000_000) * pricing["input"] + \
               (output_tokens / 1_000_000) * pricing["output"]

    async def _log_api_call(
        self,
        input_tokens: int,
        output_tokens: int,
        total_tokens: Optional[int] = None,
        cost_usd: Optional[float] = None,
        request_timestamp: Optional[datetime] = None,
        response_timestamp: Optional[datetime] = None,
        duration_ms: int = 0,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> int:
        now = datetime.now(timezone.utc)
        record = AIApiCall(
            model=self.model,
            operation="commit_summary_generation",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens if total_tokens is not None else (input_tokens + output_tokens),
            cost_usd=Decimal(str(cost_usd or self._calculate_cost(input_tokens, output_tokens))),
            request_timestamp=request_timestamp or now,
            response_timestamp=response_timestamp or now,
            duration_ms=duration_ms,
            success=success,
            error_message=error_message,
        )
        self.session.add(record)
        await self.session.flush()
        await self.session.commit()
        return record.id
