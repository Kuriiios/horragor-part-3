"""Selenium acquisition for dynamic Rotten Tomatoes horror listings."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from ..models import MovieRecord
from ..normalization import normalize_movie_record
from .base import SourceDependencyError

_SCORE_PATTERN = re.compile(r"(\d{1,3})\s*%")
_YEAR_PATTERN = re.compile(r"\b((?:18|19|20)\d{2})\b")


class RottenTomatoesSource:
    name = "rotten_tomatoes"

    def __init__(
        self,
        *,
        url: str = "https://www.rottentomatoes.com/browse/movies_at_home/genres:horror",
        max_items: int = 100,
        timeout_seconds: float = 15.0,
        driver_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.url = url
        self.max_items = max(1, min(int(max_items), 500))
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.driver_factory = driver_factory

    def _create_driver(self) -> Any:
        if self.driver_factory is not None:
            return self.driver_factory()
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
        except ImportError as exc:
            raise SourceDependencyError(
                "Install the ingestion extra to use Rotten Tomatoes scraping"
            ) from exc
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        return webdriver.Chrome(options=options)

    @staticmethod
    def _optional_text(card: Any, by: Any, selector: str) -> str | None:
        try:
            return str(card.find_element(by.CSS_SELECTOR, selector).text).strip() or None
        except Exception:
            return None

    @staticmethod
    def _optional_attribute(
        card: Any,
        by: Any,
        selector: str,
        attribute: str,
    ) -> str | None:
        try:
            value = card.find_element(by.CSS_SELECTOR, selector).get_attribute(attribute)
            return str(value).strip() if value else None
        except Exception:
            return None

    def _critics_consensus(self, driver: Any, by: Any, source_url: str | None) -> str | None:
        if not source_url:
            return None
        driver.get(source_url)
        for selector in (
            "[data-qa='score-panel-critics-consensus']",
            "[data-qa='critics-consensus']",
            ".critics-consensus",
        ):
            consensus = self._optional_text(driver, by, selector)
            if consensus:
                return consensus
        return None

    def extract(self) -> list[MovieRecord]:
        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support import expected_conditions as conditions
            from selenium.webdriver.support.ui import WebDriverWait
        except ImportError as exc:
            raise SourceDependencyError(
                "Install the ingestion extra to use Rotten Tomatoes scraping"
            ) from exc

        driver = self._create_driver()
        try:
            driver.get(self.url)
            cards = WebDriverWait(driver, self.timeout_seconds).until(
                conditions.presence_of_all_elements_located(
                    (By.CSS_SELECTOR, "[data-qa='discovery-media-list-item']")
                )
            )
            candidates: list[dict[str, Any]] = []
            for card in cards[: self.max_items]:
                title = self._optional_text(card, By, "[data-qa='discovery-media-list-item-title']")
                score_text = self._optional_text(card, By, "score-pairs") or str(card.text)
                scores = [int(value) for value in _SCORE_PATTERN.findall(score_text)[:2]]
                release_text = self._optional_text(
                    card,
                    By,
                    "[data-qa='discovery-media-list-item-start-date']",
                )
                year_match = _YEAR_PATTERN.search(release_text or "")
                source_url = self._optional_attribute(card, By, "a", "href")
                candidates.append(
                    {
                    "title": title,
                    "genres": ["Horror"],
                    "year": year_match.group(1) if year_match else None,
                    "tomatometer_score": scores[0] if scores else None,
                    "audience_score": scores[1] if len(scores) > 1 else None,
                    "source_url": source_url,
                }
                )

            records: list[MovieRecord] = []
            for raw in candidates:
                raw["critics_consensus"] = self._critics_consensus(
                    driver,
                    By,
                    raw.get("source_url"),
                )
                record = normalize_movie_record(raw, self.name)
                if record is not None:
                    records.append(record)
            return records
        finally:
            driver.quit()