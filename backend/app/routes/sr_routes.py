"""Spaced Repetition routes using the SM-2 algorithm."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List
from uuid import UUID
from datetime import datetime, timezone, timedelta
from app.database import get_db
from app.auth import get_current_user
from app.models import User, Note, Folder, FlashCard, SRSettings
from app.schemas import (
    FlashCardResponse, FlashCardReview, ReviewSessionResponse,
    SRSettingsUpdate, SRSettingsResponse,
)
from app.services.ai_service import generate_flashcards

router = APIRouter(prefix="/sr", tags=["spaced-repetition"])


# ── SM-2 Algorithm ────────────────────────────────────────────────────

def sm2_update(card: FlashCard, quality: int, min_easiness: float = 1.3):
    """
    SM-2 algorithm implementation.
    quality: 0-5 (0=complete blackout, 5=perfect)
    """
    now = datetime.now(timezone.utc)
    card.last_review = now

    if quality < 3:
        # Failed: reset repetitions, short interval
        card.repetitions = 0
        card.interval = 1
    else:
        if card.repetitions == 0:
            card.interval = 1
        elif card.repetitions == 1:
            card.interval = 6
        else:
            card.interval = round(card.interval * card.easiness)
        card.repetitions += 1

    # Update easiness factor
    card.easiness = max(
        min_easiness,
        card.easiness + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    )

    card.next_review = now + timedelta(days=card.interval)


# ── Settings ──────────────────────────────────────────────────────────

@router.get("/settings", response_model=SRSettingsResponse)
async def get_sr_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(SRSettings).where(SRSettings.user_id == current_user.id)
    )
    settings = result.scalar_one_or_none()
    if settings:
        return settings
    return SRSettingsResponse()


@router.put("/settings", response_model=SRSettingsResponse)
async def update_sr_settings(
    data: SRSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(SRSettings).where(SRSettings.user_id == current_user.id)
    )
    settings = result.scalar_one_or_none()
    if not settings:
        settings = SRSettings(user_id=current_user.id)
        db.add(settings)

    if data.cards_per_session is not None:
        settings.cards_per_session = data.cards_per_session
    if data.min_easiness is not None:
        settings.min_easiness = data.min_easiness
    if data.max_new_cards_per_day is not None:
        settings.max_new_cards_per_day = data.max_new_cards_per_day

    await db.flush()
    await db.refresh(settings)
    await db.commit()
    return settings


# ── Flashcard Generation ──────────────────────────────────────────────

@router.post("/generate/{note_id}", response_model=List[FlashCardResponse])
async def generate_cards_for_note(
    note_id: UUID,
    max_cards: int = 5,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate flashcards from a note using AI."""
    note = await db.get(Note, note_id)
    if not note or note.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")

    cards_data = await generate_flashcards(note.title, note.content, max_cards)

    created_cards = []
    for cd in cards_data:
        card = FlashCard(
            note_id=note_id,
            user_id=current_user.id,
            question=cd["question"],
            answer=cd["answer"],
        )
        db.add(card)
        await db.flush()
        await db.refresh(card)
        created_cards.append(FlashCardResponse(
            id=card.id,
            note_id=card.note_id,
            question=card.question,
            answer=card.answer,
            easiness=card.easiness,
            interval=card.interval,
            repetitions=card.repetitions,
            next_review=card.next_review,
            last_review=card.last_review,
            note_title=note.title,
        ))

    await db.commit()
    return created_cards


@router.post("/generate-folder/{folder_id}", response_model=List[FlashCardResponse])
async def generate_cards_for_folder(
    folder_id: UUID,
    max_cards_per_note: int = 3,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate flashcards for all notes in a folder."""
    folder = await db.get(Folder, folder_id)
    if not folder or folder.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Folder not found")

    notes_result = await db.execute(
        select(Note).where(Note.folder_id == folder_id, Note.user_id == current_user.id)
    )
    notes = notes_result.scalars().all()

    all_cards = []
    for note in notes:
        cards_data = await generate_flashcards(note.title, note.content, max_cards_per_note)
        for cd in cards_data:
            card = FlashCard(
                note_id=note.id,
                user_id=current_user.id,
                question=cd["question"],
                answer=cd["answer"],
            )
            db.add(card)
            await db.flush()
            await db.refresh(card)
            all_cards.append(FlashCardResponse(
                id=card.id,
                note_id=card.note_id,
                question=card.question,
                answer=card.answer,
                easiness=card.easiness,
                interval=card.interval,
                repetitions=card.repetitions,
                next_review=card.next_review,
                last_review=card.last_review,
                note_title=note.title,
            ))

    await db.commit()
    return all_cards


# ── Review Session ────────────────────────────────────────────────────

@router.get("/review", response_model=ReviewSessionResponse)
async def get_review_session(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get cards due for review (SM-2: next_review <= now)."""
    now = datetime.now(timezone.utc)

    # Get SR settings
    settings_result = await db.execute(
        select(SRSettings).where(SRSettings.user_id == current_user.id)
    )
    sr_settings = settings_result.scalar_one_or_none()
    cards_per_session = sr_settings.cards_per_session if sr_settings else 20

    # Cards due for review
    due_result = await db.execute(
        select(FlashCard)
        .where(
            FlashCard.user_id == current_user.id,
            FlashCard.next_review <= now,
        )
        .order_by(FlashCard.next_review)
        .limit(cards_per_session)
    )
    due_cards = due_result.scalars().all()

    # Total due count
    total_due_result = await db.execute(
        select(func.count(FlashCard.id))
        .where(FlashCard.user_id == current_user.id, FlashCard.next_review <= now)
    )
    total_due = total_due_result.scalar() or 0

    # New cards today count
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    new_today_result = await db.execute(
        select(func.count(FlashCard.id))
        .where(
            FlashCard.user_id == current_user.id,
            FlashCard.created_at >= today_start,
            FlashCard.repetitions == 0,
        )
    )
    new_today = new_today_result.scalar() or 0

    # Enrich with note titles
    card_responses = []
    for card in due_cards:
        note = await db.get(Note, card.note_id)
        card_responses.append(FlashCardResponse(
            id=card.id,
            note_id=card.note_id,
            question=card.question,
            answer=card.answer,
            easiness=card.easiness,
            interval=card.interval,
            repetitions=card.repetitions,
            next_review=card.next_review,
            last_review=card.last_review,
            note_title=note.title if note else None,
        ))

    return ReviewSessionResponse(
        cards=card_responses,
        total_due=total_due,
        new_today=new_today,
    )


@router.post("/review", response_model=FlashCardResponse)
async def submit_review(
    review: FlashCardReview,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Submit a review for a flashcard (SM-2 quality 0-5)."""
    card = await db.get(FlashCard, review.card_id)
    if not card or card.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Card not found")

    if not 0 <= review.quality <= 5:
        raise HTTPException(status_code=400, detail="Quality must be 0-5")

    # Get min easiness from settings
    settings_result = await db.execute(
        select(SRSettings).where(SRSettings.user_id == current_user.id)
    )
    sr_settings = settings_result.scalar_one_or_none()
    min_easiness = sr_settings.min_easiness if sr_settings else 1.3

    sm2_update(card, review.quality, min_easiness)
    await db.flush()
    await db.refresh(card)

    note = await db.get(Note, card.note_id)

    await db.commit()
    return FlashCardResponse(
        id=card.id,
        note_id=card.note_id,
        question=card.question,
        answer=card.answer,
        easiness=card.easiness,
        interval=card.interval,
        repetitions=card.repetitions,
        next_review=card.next_review,
        last_review=card.last_review,
        note_title=note.title if note else None,
    )


# ── Card Management ───────────────────────────────────────────────────

@router.get("/cards", response_model=List[FlashCardResponse])
async def list_all_cards(
    note_id: UUID = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all flashcards, optionally filtered by note."""
    query = select(FlashCard).where(FlashCard.user_id == current_user.id)
    if note_id:
        query = query.where(FlashCard.note_id == note_id)
    query = query.order_by(FlashCard.next_review)

    result = await db.execute(query)
    cards = result.scalars().all()

    card_responses = []
    for card in cards:
        note = await db.get(Note, card.note_id)
        card_responses.append(FlashCardResponse(
            id=card.id,
            note_id=card.note_id,
            question=card.question,
            answer=card.answer,
            easiness=card.easiness,
            interval=card.interval,
            repetitions=card.repetitions,
            next_review=card.next_review,
            last_review=card.last_review,
            note_title=note.title if note else None,
        ))

    return card_responses


@router.delete("/cards/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_card(
    card_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    card = await db.get(FlashCard, card_id)
    if not card or card.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Card not found")
    await db.delete(card)
    await db.commit()
