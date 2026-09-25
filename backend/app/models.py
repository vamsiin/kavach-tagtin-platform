"""
SQLAlchemy persistence layer. This is intentionally a thin adapter: it maps ORM rows
to/from the plain dataclasses in app.domain, which is what the rules engine and ToC
cross-validator actually operate on (see domain.py docstring for why). Routers should
convert to domain objects immediately after a DB read and convert back immediately
before a DB write -- domain objects should be what flows through business logic.
"""
from sqlalchemy import (
    Column, Integer, String, Float, ForeignKey, DateTime, Text, Boolean
)
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from .database import Base
from . import domain


class StationORM(Base):
    __tablename__ = "stations"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    kavach_station_id = Column(String, unique=True, nullable=False)
    sip_drawing_number = Column(String, nullable=True)
    kavach_version = Column(String, nullable=True)
    sip_version = Column(String, nullable=True)
    guideline_version = Column(String, nullable=True)
    drawn_to_scale = Column(Boolean, default=True)
    not_to_scale_note_present = Column(Boolean, default=False)
    status = Column(String, default="draft")
    created_by = Column(String, nullable=True)  # username of the creator
    assigned_checker = Column(String, nullable=True)  # username of the checker this was submitted to
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    elements = relationship("ElementORM", back_populates="station", cascade="all, delete-orphan")
    tags = relationship("TagORM", back_populates="station", cascade="all, delete-orphan")
    tins = relationship("TINORM", back_populates="station", cascade="all, delete-orphan")
    revisions = relationship("RevisionORM", back_populates="station", cascade="all, delete-orphan")

    def to_domain(self) -> domain.Station:
        return domain.Station(
            id=self.id, name=self.name, kavach_station_id=self.kavach_station_id,
            sip_drawing_number=self.sip_drawing_number or "",
            kavach_version=self.kavach_version or "", sip_version=self.sip_version or "",
            guideline_version=self.guideline_version or "",
            created_by=self.created_by, assigned_checker=self.assigned_checker,
            drawn_to_scale=bool(self.drawn_to_scale),
            not_to_scale_note_present=bool(self.not_to_scale_note_present),
            status=self.status,
        )

    @property
    def layout_version(self) -> str:
        """Duplicated logic from domain.Station.layout_version (same formula,
        independent of kavach/sip/guideline version) so this property is directly
        accessible on the ORM object itself -- this is what lets _station_out() in
        routers/stations.py use Pydantic's from_attributes=True to build the
        response schema instead of manually listing every field by hand, which is
        what caused two separate real bugs (created_by, then assigned_checker,
        both silently missing from API responses after being added to the model)
        before this property existed."""
        if not (self.kavach_version and self.sip_version and self.guideline_version):
            return "INCOMPLETE"
        return f"{self.kavach_version}.{self.sip_version}.{self.guideline_version}"


class ElementORM(Base):
    __tablename__ = "elements"

    id = Column(Integer, primary_key=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False)
    element_ref = Column(String, nullable=False)
    element_type = Column(String, nullable=False)
    location_km = Column(Float, nullable=False)
    direction = Column(String, nullable=True)
    remarks = Column(Text, nullable=True)

    station = relationship("StationORM", back_populates="elements")

    def to_domain(self) -> domain.Element:
        return domain.Element(
            id=self.id, element_ref=self.element_ref, element_type=self.element_type,
            location_km=self.location_km, direction=self.direction,
            remarks=self.remarks or "",
        )


class TagORM(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False)
    tag_ref = Column(String, nullable=False)
    tag_number = Column(Integer, nullable=True)
    tag_type = Column(String, nullable=False)
    direction = Column(String, nullable=True)
    location_km = Column(Float, nullable=False)
    tin_no = Column(Integer, nullable=True)
    linked_element_id = Column(Integer, ForeignKey("elements.id"), nullable=True)
    is_duplicate = Column(Boolean, default=False)
    pair_group_id = Column(String, nullable=True)
    legend_shape = Column(String, nullable=True)
    exit_set = Column(String, nullable=True)
    is_border_tag = Column(Boolean, default=False)
    remarks = Column(Text, nullable=True)

    station = relationship("StationORM", back_populates="tags")

    def to_domain(self) -> domain.Tag:
        return domain.Tag(
            id=self.id, tag_ref=self.tag_ref, tag_type=self.tag_type,
            location_km=self.location_km, tag_number=self.tag_number,
            direction=self.direction, tin_no=self.tin_no,
            linked_element_id=self.linked_element_id, is_duplicate=bool(self.is_duplicate),
            pair_group_id=self.pair_group_id, legend_shape=self.legend_shape,
            exit_set=self.exit_set, is_border_tag=bool(self.is_border_tag),
            remarks=self.remarks or "",
        )


class TINORM(Base):
    __tablename__ = "tins"

    id = Column(Integer, primary_key=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False)
    tin_no = Column(Integer, nullable=False)
    section_type = Column(String, nullable=False)
    color = Column(String, nullable=True)
    start_km = Column(Float, nullable=False)
    end_km = Column(Float, nullable=False)
    direction = Column(String, nullable=True)
    is_non_kavach_territory = Column(Boolean, default=False)
    remarks = Column(Text, nullable=True)

    station = relationship("StationORM", back_populates="tins")

    def to_domain(self) -> domain.TIN:
        return domain.TIN(
            tin_no=self.tin_no, section_type=self.section_type, color=self.color,
            start_km=self.start_km, end_km=self.end_km, direction=self.direction,
            is_non_kavach_territory=bool(self.is_non_kavach_territory),
            remarks=self.remarks or "",
        )


class RevisionORM(Base):
    __tablename__ = "revisions"

    id = Column(Integer, primary_key=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False)
    rev_no = Column(String, nullable=False)
    date = Column(String, nullable=True)
    description = Column(Text, nullable=False)

    station = relationship("StationORM", back_populates="revisions")


class UserORM(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False, index=True)
    full_name = Column(String, nullable=False)
    email = Column(String, nullable=True)
    role = Column(String, nullable=False)  # designer | checker | approver | admin
    password_hash = Column(String, nullable=False)
    password_salt = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)

    def to_domain(self) -> domain.User:
        return domain.User(
            id=self.id, username=self.username, full_name=self.full_name,
            email=self.email or "", role=self.role, password_hash=self.password_hash,
            password_salt=self.password_salt, is_active=bool(self.is_active),
        )


class WorkflowEventORM(Base):
    __tablename__ = "workflow_events"

    id = Column(Integer, primary_key=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False)
    from_status = Column(String, nullable=False)
    to_status = Column(String, nullable=False)
    action = Column(String, nullable=False)
    actor_username = Column(String, nullable=False)
    actor_role = Column(String, nullable=False)
    comment = Column(Text, nullable=True)
    timestamp = Column(String, nullable=False)
    verification_fail_count = Column(Integer, nullable=True)
    target_username = Column(String, nullable=True)  # e.g. checker a submission was assigned to

    def to_domain(self) -> domain.WorkflowEvent:
        return domain.WorkflowEvent(
            id=self.id, station_id=self.station_id, from_status=self.from_status,
            to_status=self.to_status, action=self.action,
            actor_username=self.actor_username, actor_role=self.actor_role,
            comment=self.comment or "", timestamp=self.timestamp,
            verification_fail_count=self.verification_fail_count,
            target_username=self.target_username,
        )

