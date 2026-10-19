"""Normalized SQLAlchemy 2.0 model for HorRAGor's source of truth."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class Movie(Base):
    __tablename__ = "movies"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tmdb_id: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)
    imdb_id: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    release_date: Mapped[date | None] = mapped_column(Date, index=True)
    overview: Mapped[str | None] = mapped_column(Text)
    tagline: Mapped[str | None] = mapped_column(Text)
    vote_average: Mapped[float | None] = mapped_column(Float)
    imdb_rating: Mapped[float | None] = mapped_column(Float)
    tomatometer_score: Mapped[float | None] = mapped_column(Float)
    audience_score: Mapped[float | None] = mapped_column(Float)
    popularity: Mapped[float | None] = mapped_column(Float)
    poster_path: Mapped[str | None] = mapped_column(Text)
    budget: Mapped[int | None] = mapped_column(BigInteger)
    revenue: Mapped[int | None] = mapped_column(BigInteger)
    runtime: Mapped[int | None] = mapped_column(Integer)
    overview_embedding: Mapped[list[float] | None] = mapped_column(Vector(768))
    extra_attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Source(Base):
    __tablename__ = "sources"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)


class MovieSource(Base):
    __tablename__ = "movie_sources"

    movie_id: Mapped[str] = mapped_column(
        ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True
    )
    source_name: Mapped[str] = mapped_column(
        ForeignKey("sources.name", ondelete="RESTRICT"), primary_key=True
    )
    source_record_id: Mapped[str | None] = mapped_column(String(128))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Genre(Base):
    __tablename__ = "genres"

    name: Mapped[str] = mapped_column(String(128), primary_key=True)


class MovieGenre(Base):
    __tablename__ = "movie_genres"

    movie_id: Mapped[str] = mapped_column(
        ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True
    )
    genre_name: Mapped[str] = mapped_column(
        ForeignKey("genres.name", ondelete="RESTRICT"), primary_key=True
    )


class Person(Base):
    __tablename__ = "people"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False, index=True)


class Credit(Base):
    __tablename__ = "credits"
    __table_args__ = (
        UniqueConstraint(
            "movie_id",
            "person_id",
            "credit_type",
            "role_name",
            name="uq_credit_identity",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    movie_id: Mapped[str] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"))
    person_id: Mapped[str] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"))
    credit_type: Mapped[str] = mapped_column(String(16))
    role_name: Mapped[str] = mapped_column(String(256), default="")
    billing_order: Mapped[int | None] = mapped_column(Integer)