from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.dependencies import (
    CurrentUser,
    DB,
    require_workspace_admin,
    require_workspace_member,
    require_team_admin,
)
from app.core.skills import normalize_skills, parse_skills
from app.core.profile import profile_completion
from app.models import ChatConversation, ChatParticipant, ChatType, Comment, Department, Designation, GlobalDepartment, GlobalDesignation, Project, Task, Team, TeamManager, TeamMember, User, UserProfile, Workspace, WorkspaceMember, WorkspaceRole
from app.schemas import (
    MemberAdd,
    MemberAccessUpdate,
    MemberRead,
    MemberProfessionalUpdate,
    DesignationCreate,
    DesignationRead,
    DesignationUpdate,
    DepartmentCreate,
    DepartmentRead,
    DepartmentUpdate,
    TeamCreate,
    TeamUpdate,
    TeamMemberAdd,
    TeamMemberUpdate,
    TeamMemberRead,
    TeamRead,
    UserRead,
    UserDirectoryRead,
    UserProfileRead,
    UserProfileUpdate,
    SkillMemberRead,
    WorkspaceCreate,
    WorkspaceDeleteConfirm,
    WorkspaceRead,
    WorkspaceUpdate,
)

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])


def commit_catalog_change(db: DB, duplicate_message: str) -> None:
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=duplicate_message) from error


def validate_profile_catalog(
    db: DB, designation_name: str | None, department_name: str | None
) -> None:
    if department_name and db.scalar(select(GlobalDepartment.id).where(
        GlobalDepartment.name == department_name
    )) is None:
        raise HTTPException(status_code=400, detail="Select a valid department")
    if designation_name:
        if not department_name:
            raise HTTPException(status_code=400, detail="A designation requires a department")
        valid = db.scalar(
            select(GlobalDesignation.id)
            .join(GlobalDepartment, GlobalDepartment.id == GlobalDesignation.department_id)
            .where(
                GlobalDesignation.name == designation_name,
                GlobalDepartment.name == department_name,
            )
        )
        if valid is None:
            raise HTTPException(
                status_code=400,
                detail="Select a designation that belongs to the selected department",
            )


def validate_team_manager(
    db: DB, workspace_id: int, user_id: int, designation_name: str
) -> None:
    user = db.scalar(select(User).where(User.id == user_id, User.is_active.is_(True)))
    designation = db.scalar(select(GlobalDesignation.id).where(
        GlobalDesignation.name == designation_name.strip(),
    ))
    if user is None:
        raise HTTPException(status_code=400, detail="Select an active registered user as manager")
    if designation is None:
        raise HTTPException(status_code=400, detail="Select a valid manager designation")
    ensure_workspace_access(db, workspace_id, user_id)


def ensure_workspace_access(db: DB, workspace_id: int, user_id: int) -> WorkspaceMember:
    member = db.scalar(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == user_id,
    ))
    if member is None:
        member = WorkspaceMember(
            workspace_id=workspace_id,
            user_id=user_id,
            role=WorkspaceRole.member,
            is_active=True,
        )
        db.add(member)
        db.flush()
    elif not member.is_active:
        member.is_active = True
    return member


@router.get("/{workspace_id}/departments", response_model=list[DepartmentRead])
def list_departments(workspace_id: int, db: DB, current_user: CurrentUser) -> list[GlobalDepartment]:
    require_workspace_member(db, workspace_id, current_user.id)
    return list(db.scalars(select(GlobalDepartment).order_by(GlobalDepartment.name)).all())


@router.post("/{workspace_id}/departments", response_model=DepartmentRead, status_code=201)
def create_department(
    workspace_id: int, payload: DepartmentCreate, db: DB, current_user: CurrentUser
) -> GlobalDepartment:
    require_workspace_admin(db, workspace_id, current_user.id)
    name = payload.name.strip()
    if db.scalar(select(GlobalDepartment.id).where(func.lower(GlobalDepartment.name) == name.casefold())):
        raise HTTPException(status_code=409, detail="Department already exists")
    department = GlobalDepartment(name=name, description=payload.description)
    db.add(department);commit_catalog_change(db, "Department already exists");db.refresh(department)
    return department


@router.patch("/{workspace_id}/departments/{department_id}", response_model=DepartmentRead)
def update_department(
    workspace_id: int, department_id: int, payload: DepartmentUpdate,
    db: DB, current_user: CurrentUser
) -> GlobalDepartment:
    require_workspace_admin(db, workspace_id, current_user.id)
    department = db.get(GlobalDepartment, department_id)
    if department is None:
        raise HTTPException(status_code=404, detail="Department not found")
    values = payload.model_dump(exclude_unset=True)
    old_name = department.name
    if values.get("name") is not None:
        values["name"] = values["name"].strip()
        if db.scalar(select(GlobalDepartment.id).where(
            func.lower(GlobalDepartment.name) == values["name"].casefold(), GlobalDepartment.id != department_id
        )):
            raise HTTPException(status_code=409, detail="Department already exists")
    for field, value in values.items(): setattr(department, field, value)
    new_name = values.get("name", old_name)
    if new_name != old_name:
        for profile in db.scalars(select(UserProfile).where(UserProfile.department == old_name)).all():
            profile.department = new_name
    commit_catalog_change(db, "Department already exists");db.refresh(department)
    return department


@router.delete("/{workspace_id}/departments/{department_id}", status_code=204)
def delete_department(
    workspace_id: int, department_id: int, db: DB, current_user: CurrentUser
) -> None:
    require_workspace_admin(db, workspace_id, current_user.id)
    department = db.get(GlobalDepartment, department_id)
    if department is None:
        raise HTTPException(status_code=404, detail="Department not found")
    designation_names = list(db.scalars(select(GlobalDesignation.name).where(
        GlobalDesignation.department_id == department.id
    )).all())
    for profile in db.scalars(select(UserProfile).where(
        (UserProfile.department == department.name) |
        (UserProfile.professional_title.in_(designation_names) if designation_names else False)
    )).all():
        if profile.department == department.name:
            profile.department = None
        if profile.professional_title in designation_names:
            profile.professional_title = None
    if designation_names:
        for allocation in db.scalars(select(TeamMember).where(
            TeamMember.designation.in_(designation_names)
        )).all():
            allocation.designation = ""
        for manager in db.scalars(select(TeamManager).where(
            TeamManager.designation.in_(designation_names)
        )).all():
            manager.designation = ""
    db.delete(department)
    db.commit()


@router.get("/{workspace_id}/designations", response_model=list[DesignationRead])
def list_designations(workspace_id: int, db: DB, current_user: CurrentUser) -> list[GlobalDesignation]:
    require_workspace_member(db, workspace_id, current_user.id)
    return list(db.scalars(select(GlobalDesignation).options(
        selectinload(GlobalDesignation.department)
    ).order_by(GlobalDesignation.name)).all())


@router.post("/{workspace_id}/designations", response_model=DesignationRead, status_code=201)
def create_designation(
    workspace_id: int, payload: DesignationCreate, db: DB, current_user: CurrentUser
) -> GlobalDesignation:
    require_workspace_admin(db, workspace_id, current_user.id)
    name = payload.name.strip()
    department = db.get(GlobalDepartment, payload.department_id)
    if department is None:
        raise HTTPException(status_code=400, detail="Select a valid department")
    exists = db.scalar(select(GlobalDesignation).where(
        func.lower(GlobalDesignation.name) == name.casefold()
    ))
    if exists:
        raise HTTPException(status_code=409, detail="Designation already exists")
    designation = GlobalDesignation(
        name=name, description=payload.description, department_id=department.id
    )
    db.add(designation);commit_catalog_change(db, "Designation already exists");db.refresh(designation)
    return designation


@router.patch("/{workspace_id}/designations/{designation_id}", response_model=DesignationRead)
def update_designation(
    workspace_id: int, designation_id: int, payload: DesignationUpdate,
    db: DB, current_user: CurrentUser
) -> GlobalDesignation:
    require_workspace_admin(db, workspace_id, current_user.id)
    designation = db.get(GlobalDesignation, designation_id)
    if designation is None:
        raise HTTPException(status_code=404, detail="Designation not found")
    values = payload.model_dump(exclude_unset=True)
    old_name = designation.name
    if "department_id" in values:
        if values["department_id"] is None or db.get(GlobalDepartment, values["department_id"]) is None:
            raise HTTPException(status_code=400, detail="Select a valid department")
    if values.get("name") is not None:
        values["name"] = values["name"].strip()
        duplicate = db.scalar(select(GlobalDesignation.id).where(
            func.lower(GlobalDesignation.name) == values["name"].casefold(), GlobalDesignation.id != designation_id
        ))
        if duplicate:
            raise HTTPException(status_code=409, detail="Designation already exists")
    for field, value in values.items(): setattr(designation, field, value)
    new_name = values.get("name", old_name)
    if new_name != old_name:
        allocations = db.scalars(select(TeamMember).where(
            TeamMember.designation == old_name
        )).all()
        for allocation in allocations: allocation.designation = designation.name
        managers = db.scalars(select(TeamManager).where(
            TeamManager.designation == old_name
        )).all()
        for manager in managers: manager.designation = designation.name
        profiles = db.scalars(select(UserProfile).where(
            UserProfile.professional_title == old_name,
        )).all()
        for profile in profiles: profile.professional_title = designation.name
    commit_catalog_change(db, "Designation already exists");db.refresh(designation)
    return designation


@router.delete("/{workspace_id}/designations/{designation_id}", status_code=204)
def delete_designation(
    workspace_id: int, designation_id: int, db: DB, current_user: CurrentUser
) -> None:
    require_workspace_admin(db, workspace_id, current_user.id)
    designation = db.get(GlobalDesignation, designation_id)
    if designation is None:
        raise HTTPException(status_code=404, detail="Designation not found")
    for allocation in db.scalars(select(TeamMember).where(
        TeamMember.designation == designation.name
    )).all():
        allocation.designation = ""
    for manager in db.scalars(select(TeamManager).where(
        TeamManager.designation == designation.name
    )).all():
        manager.designation = ""
    for profile in db.scalars(select(UserProfile).where(
        UserProfile.professional_title == designation.name
    )).all():
        profile.professional_title = None
    db.delete(designation)
    db.commit()


@router.post("", response_model=WorkspaceRead, status_code=201)
def create_workspace(
    payload: WorkspaceCreate, db: DB, current_user: CurrentUser
) -> Workspace:
    workspace = Workspace(
        name=payload.name.strip(),
        description=payload.description,
        owner_id=current_user.id,
    )
    db.add(workspace)
    db.flush()
    db.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=current_user.id,
            role=WorkspaceRole.admin,
        )
    )
    db.commit()
    db.refresh(workspace)
    return workspace


@router.get("", response_model=list[WorkspaceRead])
def list_workspaces(db: DB, current_user: CurrentUser) -> list[WorkspaceRead]:
    rows = db.execute(
        select(Workspace, WorkspaceMember.role)
        .join(WorkspaceMember)
        .where(
            WorkspaceMember.user_id == current_user.id,
            WorkspaceMember.is_active.is_(True),
        )
        .order_by(Workspace.created_at.desc())
    ).all()
    visible = []
    for workspace, role in rows:
        if role != WorkspaceRole.admin:
            allocated = db.scalar(
                select(TeamMember.id)
                .join(Team, Team.id == TeamMember.team_id)
                .where(
                    Team.workspace_id == workspace.id,
                    TeamMember.user_id == current_user.id,
                )
            )
            managed = db.scalar(select(Project.id).where(
                Project.workspace_id == workspace.id,
                Project.project_manager_id == current_user.id,
            ))
            direct_chat = db.scalar(
                select(ChatParticipant.id)
                .join(ChatConversation, ChatConversation.id == ChatParticipant.conversation_id)
                .where(
                    ChatConversation.workspace_id == workspace.id,
                    ChatConversation.chat_type == ChatType.direct,
                    ChatParticipant.user_id == current_user.id,
                )
            )
            if allocated is None and managed is None and direct_chat is None:
                continue
        visible.append(
            WorkspaceRead.model_validate(workspace).model_copy(update={"role": role})
        )
    return visible


@router.delete("/{workspace_id}", status_code=204)
def delete_workspace(
    workspace_id: int,
    payload: WorkspaceDeleteConfirm,
    db: DB,
    current_user: CurrentUser,
) -> None:
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if workspace.owner_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Only the workspace owner can delete this workspace",
        )
    if payload.workspace_name != workspace.name:
        raise HTTPException(
            status_code=400,
            detail="Workspace name confirmation does not match",
        )
    db.delete(workspace)
    db.commit()


@router.patch("/{workspace_id}", response_model=WorkspaceRead)
def update_workspace(
    workspace_id: int,
    payload: WorkspaceUpdate,
    db: DB,
    current_user: CurrentUser,
) -> Workspace:
    require_workspace_admin(db, workspace_id, current_user.id)
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(
            workspace,
            field,
            value.strip() if field == "name" and value is not None else value,
        )
    db.commit()
    db.refresh(workspace)
    return workspace


@router.get("/{workspace_id}", response_model=WorkspaceRead)
def get_workspace(
    workspace_id: int, db: DB, current_user: CurrentUser
) -> Workspace:
    require_workspace_member(db, workspace_id, current_user.id)
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


@router.post("/{workspace_id}/members", response_model=MemberRead, status_code=201)
def add_member(
    workspace_id: int,
    payload: MemberAdd,
    db: DB,
    current_user: CurrentUser,
) -> WorkspaceMember:
    require_workspace_admin(db, workspace_id, current_user.id)
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None:
        raise HTTPException(
            status_code=404, detail="A registered user with that email was not found"
        )
    if not user.is_active:
        raise HTTPException(
            status_code=409, detail="Approve this registration before adding the user"
        )
    existing = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="User is already a member")
    member = WorkspaceMember(
        workspace_id=workspace_id, user_id=user.id, role=payload.role
    )
    db.add(member)
    db.commit()
    return db.scalar(
        select(WorkspaceMember)
        .options(selectinload(WorkspaceMember.user).selectinload(User.profile))
        .where(WorkspaceMember.id == member.id)
    )


@router.get("/{workspace_id}/members", response_model=list[MemberRead])
def list_members(
    workspace_id: int, db: DB, current_user: CurrentUser
) -> list[WorkspaceMember]:
    membership = require_workspace_member(db, workspace_id, current_user.id)
    query = (
        select(WorkspaceMember)
        .options(selectinload(WorkspaceMember.user).selectinload(User.profile))
        .where(WorkspaceMember.workspace_id == workspace_id)
    )
    if membership.role != WorkspaceRole.admin:
        accessible_projects = select(TeamMember.project_id).join(Project).where(
            TeamMember.user_id == current_user.id,
            Project.workspace_id == workspace_id,
        )
        visible_users = select(TeamMember.user_id).where(
            TeamMember.project_id.in_(accessible_projects)
        )
        query = query.where(
            (WorkspaceMember.user_id == current_user.id) |
            WorkspaceMember.user_id.in_(visible_users)
        )
    return list(
        db.scalars(query).all()
    )


@router.get("/{workspace_id}/available-users", response_model=list[UserRead])
def list_available_users(
    workspace_id: int, db: DB, current_user: CurrentUser
) -> list[User]:
    require_workspace_admin(db, workspace_id, current_user.id)
    existing_user_ids = select(WorkspaceMember.user_id).where(
        WorkspaceMember.workspace_id == workspace_id
    )
    return list(db.scalars(
        select(User).where(
            User.is_active.is_(True), User.id.not_in(existing_user_ids)
        ).order_by(User.name, User.email)
    ).all())


@router.get("/{workspace_id}/user-directory", response_model=list[UserDirectoryRead])
def user_directory(
    workspace_id: int, db: DB, current_user: CurrentUser
) -> list[UserDirectoryRead]:
    require_workspace_admin(db, workspace_id, current_user.id)
    users = list(db.scalars(
        select(User).options(selectinload(User.profile)).order_by(
            User.is_active, User.name, User.email
        )
    ).all())
    memberships = {
        member.user_id: member for member in db.scalars(select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id
        )).all()
    }
    allocation_rows = db.execute(
        select(TeamMember.user_id, Project.name)
        .join(Team, Team.id == TeamMember.team_id)
        .join(Project, Project.id == TeamMember.project_id).where(
            Team.workspace_id == workspace_id
        ).distinct()
    ).all()
    projects_by_user: dict[int, list[str]] = {}
    for user_id, project_name in allocation_rows:
        projects_by_user.setdefault(user_id, []).append(project_name)
    return [UserDirectoryRead(
        user_id=user.id, name=user.name, email=user.email, is_active=user.is_active,
        membership_id=memberships[user.id].id if user.id in memberships else None,
        membership_is_active=memberships[user.id].is_active if user.id in memberships else None,
        role=memberships[user.id].role if user.id in memberships else None,
        professional_title=user.profile.professional_title if user.profile else None,
        department=user.profile.department if user.profile else None,
        profile_image=user.profile.profile_image if user.profile else None,
        projects=sorted(set(projects_by_user.get(user.id, []))),
        completion_percent=profile_completion(user, user.profile)[0],
        missing_fields=profile_completion(user, user.profile)[1],
    ) for user in users]


@router.get("/{workspace_id}/skill-catalog", response_model=list[str])
def skill_catalog(
    workspace_id: int, db: DB, current_user: CurrentUser
) -> list[str]:
    require_workspace_member(db, workspace_id, current_user.id)
    values = db.scalars(
        select(UserProfile.skills).join(User).where(User.is_active.is_(True))
    ).all()
    catalog: dict[str, str] = {}
    for value in values:
        for skill in parse_skills(value):
            catalog.setdefault(skill.casefold(), skill)
    return sorted(catalog.values(), key=str.casefold)


@router.get("/{workspace_id}/skill-members", response_model=list[SkillMemberRead])
def skill_members(
    workspace_id: int, db: DB, current_user: CurrentUser
) -> list[SkillMemberRead]:
    require_workspace_admin(db, workspace_id, current_user.id)
    users = db.scalars(
        select(User).options(selectinload(User.profile))
        .where(User.is_active.is_(True)).order_by(User.name, User.email)
    ).all()
    allocations = db.execute(
        select(TeamMember.user_id, TeamMember.project_id)
        .join(Team, Team.id == TeamMember.team_id)
        .where(Team.workspace_id == workspace_id)
        .distinct()
    ).all()
    projects_by_user: dict[int, list[int]] = {}
    for user_id, project_id in allocations:
        projects_by_user.setdefault(user_id, []).append(project_id)
    all_project_ids = list(db.scalars(
        select(Project.id).where(Project.workspace_id == workspace_id)
    ).all())
    admin_ids = set(db.scalars(select(WorkspaceMember.user_id).where(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.role == WorkspaceRole.admin,
        WorkspaceMember.is_active.is_(True),
    )).all())
    return [SkillMemberRead(
        user_id=user.id,
        name=user.name,
        email=user.email,
        professional_title=user.profile.professional_title if user.profile else None,
        department=user.profile.department if user.profile else None,
        profile_image=user.profile.profile_image if user.profile else None,
        skills=parse_skills(user.profile.skills if user.profile else None),
        project_ids=all_project_ids if user.id in admin_ids else projects_by_user.get(user.id, []),
    ) for user in users]


@router.patch("/{workspace_id}/members/{member_id}/access", response_model=MemberRead)
def update_member_access(
    workspace_id: int, member_id: int, payload: MemberAccessUpdate,
    db: DB, current_user: CurrentUser,
) -> WorkspaceMember:
    require_workspace_admin(db, workspace_id, current_user.id)
    member = db.scalar(select(WorkspaceMember).options(
        selectinload(WorkspaceMember.user).selectinload(User.profile)
    ).where(
        WorkspaceMember.id == member_id,
        WorkspaceMember.workspace_id == workspace_id,
    ))
    if member is None:
        raise HTTPException(status_code=404, detail="Workspace member not found")
    workspace = db.get(Workspace, workspace_id)
    if member.user_id == current_user.id and (
        payload.is_active is False or
        (payload.role is not None and payload.role != member.role)
    ):
        raise HTTPException(status_code=409, detail="You cannot change your own access")
    if payload.role is not None and workspace.owner_id == member.user_id:
        raise HTTPException(status_code=409, detail="The workspace owner must remain an admin")
    if payload.is_active is not None:
        member.is_active = payload.is_active
    if payload.role is not None:
        member.role = payload.role
    db.commit(); db.refresh(member)
    return member


@router.patch("/{workspace_id}/users/{user_id}/approve", response_model=UserRead)
def approve_registered_user(
    workspace_id: int, user_id: int, db: DB, current_user: CurrentUser
) -> User:
    require_workspace_admin(db, workspace_id, current_user.id)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Registered user not found")
    user.is_active = True
    db.commit()
    db.refresh(user)
    return user


@router.patch(
    "/{workspace_id}/members/{member_id}/professional-profile",
    response_model=MemberRead,
)
def update_member_professional_profile(
    workspace_id: int, member_id: int, payload: MemberProfessionalUpdate,
    db: DB, current_user: CurrentUser,
) -> WorkspaceMember:
    require_workspace_admin(db, workspace_id, current_user.id)
    member = db.scalar(select(WorkspaceMember).options(
        selectinload(WorkspaceMember.user).selectinload(User.profile)
    ).where(
        WorkspaceMember.id == member_id,
        WorkspaceMember.workspace_id == workspace_id,
    ))
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    if payload.professional_title and db.scalar(select(GlobalDesignation.id).where(
        GlobalDesignation.name == payload.professional_title,
    )) is None:
        raise HTTPException(status_code=400, detail="Select a valid designation")
    if payload.department and db.scalar(select(GlobalDepartment.id).where(
        GlobalDepartment.name == payload.department,
    )) is None:
        raise HTTPException(status_code=400, detail="Select a valid department")
    validate_profile_catalog(db, payload.professional_title, payload.department)
    profile = member.user.profile
    if profile is None:
        profile = UserProfile(user_id=member.user_id)
        member.user.profile = profile
    profile.professional_title = payload.professional_title
    profile.department = payload.department
    db.commit(); db.refresh(profile)
    return member


def admin_profile_response(db: DB, user: User) -> UserProfileRead:
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    allocated = db.scalars(
        select(Project.name).join(TeamMember, TeamMember.project_id == Project.id)
        .where(TeamMember.user_id == user.id).distinct()
    ).all()
    managed = db.scalars(select(Project.name).where(Project.project_manager_id == user.id)).all()
    projects = sorted(set(allocated) | set(managed))
    completion_percent, missing_fields = profile_completion(user, profile)
    return UserProfileRead(
        name=user.name, email=user.email, project_count=len(projects), projects=projects,
        profile_image=profile.profile_image if profile else None,
        phone=profile.phone if profile else None, location=profile.location if profile else None,
        bio=profile.bio if profile else None,
        professional_title=profile.professional_title if profile else None,
        department=profile.department if profile else None,
        years_experience=profile.years_experience if profile else None,
        skills=profile.skills if profile else None,
        achievements=profile.achievements if profile else None,
        completion_percent=completion_percent, missing_fields=missing_fields,
    )


def update_admin_managed_profile(
    db: DB, workspace_id: int, user: User, payload: UserProfileUpdate
) -> UserProfileRead:
    if payload.professional_title and db.scalar(select(GlobalDesignation.id).where(
        GlobalDesignation.name == payload.professional_title,
    )) is None:
        raise HTTPException(status_code=400, detail="Select a valid designation")
    if payload.department and db.scalar(select(GlobalDepartment.id).where(
        GlobalDepartment.name == payload.department,
    )) is None:
        raise HTTPException(status_code=400, detail="Select a valid department")
    validate_profile_catalog(db, payload.professional_title, payload.department)
    user.name = payload.name.strip()
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    if profile is None:
        profile = UserProfile(user_id=user.id)
        db.add(profile)
    for field, value in payload.model_dump(exclude={"name"}).items():
        if field == "skills":
            value = normalize_skills(value)
        setattr(profile, field, value.strip() if isinstance(value, str) and field != "profile_image" else value)
    db.commit(); db.refresh(user)
    return admin_profile_response(db, user)


@router.get("/{workspace_id}/users/{user_id}/profile", response_model=UserProfileRead)
def get_registered_user_profile(
    workspace_id: int, user_id: int, db: DB, current_user: CurrentUser
) -> UserProfileRead:
    require_workspace_admin(db, workspace_id, current_user.id)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Registered user not found")
    return admin_profile_response(db, user)


@router.put("/{workspace_id}/users/{user_id}/profile", response_model=UserProfileRead)
def update_registered_user_profile(
    workspace_id: int, user_id: int, payload: UserProfileUpdate,
    db: DB, current_user: CurrentUser,
) -> UserProfileRead:
    require_workspace_admin(db, workspace_id, current_user.id)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Registered user not found")
    return update_admin_managed_profile(db, workspace_id, user, payload)


@router.get("/{workspace_id}/members/{member_id}/profile", response_model=UserProfileRead)
def get_member_profile(
    workspace_id: int, member_id: int, db: DB, current_user: CurrentUser
) -> UserProfileRead:
    require_workspace_admin(db, workspace_id, current_user.id)
    member = db.scalar(select(WorkspaceMember).where(
        WorkspaceMember.id == member_id, WorkspaceMember.workspace_id == workspace_id
    ))
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    return admin_profile_response(db, db.get(User, member.user_id))


@router.put("/{workspace_id}/members/{member_id}/profile", response_model=UserProfileRead)
def update_member_profile(
    workspace_id: int, member_id: int, payload: UserProfileUpdate,
    db: DB, current_user: CurrentUser,
) -> UserProfileRead:
    require_workspace_admin(db, workspace_id, current_user.id)
    member = db.scalar(select(WorkspaceMember).where(
        WorkspaceMember.id == member_id, WorkspaceMember.workspace_id == workspace_id
    ))
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    if payload.professional_title and db.scalar(select(GlobalDesignation.id).where(
        GlobalDesignation.name == payload.professional_title,
    )) is None:
        raise HTTPException(status_code=400, detail="Select a valid designation")
    if payload.department and db.scalar(select(GlobalDepartment.id).where(
        GlobalDepartment.name == payload.department,
    )) is None:
        raise HTTPException(status_code=400, detail="Select a valid department")
    validate_profile_catalog(db, payload.professional_title, payload.department)
    user = db.get(User, member.user_id)
    user.name = payload.name.strip()
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    if profile is None:
        profile = UserProfile(user_id=user.id); db.add(profile)
    for field, value in payload.model_dump(exclude={"name"}).items():
        setattr(profile, field, value.strip() if isinstance(value, str) and field != "profile_image" else value)
    db.commit(); db.refresh(user)
    return admin_profile_response(db, user)


@router.delete("/{workspace_id}/users/{user_id}", status_code=204)
def permanently_delete_user(
    workspace_id: int, user_id: int, db: DB, current_user: CurrentUser
) -> None:
    require_workspace_admin(db, workspace_id, current_user.id)
    if user_id == current_user.id:
        raise HTTPException(status_code=409, detail="You cannot permanently delete your own account")
    membership = db.scalar(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == user_id,
    ))
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Workspace user not found")
    if db.scalar(select(Workspace.id).where(Workspace.owner_id == user_id)):
        raise HTTPException(status_code=409, detail="Transfer workspace ownership before deleting this user")
    for project in db.scalars(select(Project).where(Project.project_manager_id == user_id)).all():
        project.project_manager_id = project.workspace.owner_id
    for manager in db.scalars(select(TeamManager).where(TeamManager.user_id == user_id)).all():
        manager.user_id = manager.team.workspace.owner_id
    for task in db.scalars(select(Task).where(Task.reporter_id == user_id)).all():
        task.reporter_id = task.project.workspace.owner_id
    for task in db.scalars(select(Task).where(Task.assignee_id == user_id)).all():
        task.assignee_id = None
    for comment in db.scalars(select(Comment).where(Comment.author_id == user_id)).all():
        db.delete(comment)
    db.delete(user); db.commit()


@router.post("/{workspace_id}/teams", response_model=TeamRead, status_code=201)
def create_team(
    workspace_id: int,
    payload: TeamCreate,
    db: DB,
    current_user: CurrentUser,
) -> Team:
    require_workspace_admin(db, workspace_id, current_user.id)
    values = payload.model_dump()
    manager_user_id = values.pop("manager_user_id")
    manager_designation = values.pop("manager_designation").strip()
    validate_team_manager(db, workspace_id, manager_user_id, manager_designation)
    team = Team(workspace_id=workspace_id, **values)
    team.manager_record = TeamManager(
        user_id=manager_user_id, designation=manager_designation
    )
    db.add(team)
    db.commit()
    db.refresh(team)
    return team


@router.patch("/{workspace_id}/teams/{team_id}", response_model=TeamRead)
def update_team(
    workspace_id: int, team_id: int, payload: TeamUpdate,
    db: DB, current_user: CurrentUser,
) -> Team:
    require_workspace_admin(db, workspace_id, current_user.id)
    team = db.scalar(select(Team).where(
        Team.id == team_id, Team.workspace_id == workspace_id
    ))
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    values = payload.model_dump(exclude_unset=True)
    manager_user_id = values.pop("manager_user_id", team.manager_user_id)
    manager_designation = values.pop("manager_designation", team.manager_designation)
    if manager_user_id is None or manager_designation is None:
        raise HTTPException(status_code=400, detail="Every team requires a designated manager")
    validate_team_manager(db, workspace_id, manager_user_id, manager_designation)
    if team.manager_record is None:
        team.manager_record = TeamManager()
    team.manager_record.user_id = manager_user_id
    team.manager_record.designation = manager_designation.strip()
    for field, value in values.items():
        setattr(team, field, value.strip() if isinstance(value, str) else value)
    db.commit(); db.refresh(team)
    return team


@router.get("/{workspace_id}/teams", response_model=list[TeamRead])
def list_teams(
    workspace_id: int, db: DB, current_user: CurrentUser
) -> list[Team]:
    membership = require_workspace_member(db, workspace_id, current_user.id)
    query = (
        select(Team).options(
            selectinload(Team.manager_record).selectinload(TeamManager.user)
        ).where(Team.workspace_id == workspace_id)
    )
    if membership.role != WorkspaceRole.admin:
        visible_team_ids = select(TeamMember.team_id).where(
            TeamMember.user_id == current_user.id
        )
        query = query.where(Team.id.in_(visible_team_ids))
    return list(
        db.scalars(query.order_by(Team.created_at.desc())).all()
    )


@router.delete("/{workspace_id}/members/{member_id}", status_code=204)
def remove_member(
    workspace_id: int, member_id: int, db: DB, current_user: CurrentUser
) -> None:
    require_workspace_admin(db, workspace_id, current_user.id)
    member = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.id == member_id,
            WorkspaceMember.workspace_id == workspace_id,
        )
    )
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    if member.user_id == current_user.id:
        raise HTTPException(status_code=409, detail="You cannot remove yourself")
    allocations = list(
        db.scalars(
            select(TeamMember)
            .join(Team)
            .where(
                Team.workspace_id == workspace_id,
                TeamMember.user_id == member.user_id,
            )
        ).all()
    )
    for allocation in allocations:
        db.delete(allocation)
    db.delete(member)
    db.commit()


@router.delete("/{workspace_id}/teams/{team_id}", status_code=204)
def delete_team(
    workspace_id: int, team_id: int, db: DB, current_user: CurrentUser
) -> None:
    require_workspace_admin(db, workspace_id, current_user.id)
    team = db.scalar(
        select(Team).where(Team.id == team_id, Team.workspace_id == workspace_id)
    )
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    db.delete(team)
    db.commit()


@router.get(
    "/{workspace_id}/team-members", response_model=list[TeamMemberRead]
)
def list_team_members(
    workspace_id: int, db: DB, current_user: CurrentUser
) -> list[TeamMember]:
    membership = require_workspace_member(db, workspace_id, current_user.id)
    query = (
        select(TeamMember)
        .join(Team)
        .options(
            selectinload(TeamMember.user),
            selectinload(TeamMember.project),
        )
        .where(Team.workspace_id == workspace_id)
    )
    if membership.role != WorkspaceRole.admin:
        accessible_projects = select(TeamMember.project_id).join(Project).where(
            TeamMember.user_id == current_user.id,
            Project.workspace_id == workspace_id,
        )
        query = query.where(TeamMember.project_id.in_(accessible_projects))
    return list(
        db.scalars(query.order_by(TeamMember.created_at)).all()
    )


@router.post(
    "/{workspace_id}/teams/{team_id}/members",
    response_model=TeamMemberRead,
    status_code=201,
)
def allocate_team_member(
    workspace_id: int,
    team_id: int,
    payload: TeamMemberAdd,
    db: DB,
    current_user: CurrentUser,
) -> TeamMember:
    team = require_team_admin(db, team_id, current_user.id)
    if team.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Team not found")
    user = db.scalar(select(User).options(selectinload(User.profile)).where(
        User.id == payload.user_id, User.is_active.is_(True)
    ))
    project = db.scalar(
        select(Project).where(
            Project.id == payload.project_id,
            Project.workspace_id == workspace_id,
        )
    )
    if user is None or project is None:
        raise HTTPException(status_code=400, detail="Invalid member or project")
    completion_percent, missing_fields = profile_completion(user, user.profile)
    if completion_percent < 100:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Profile is {completion_percent}% complete. Complete these details before "
                f"team allocation: {', '.join(missing_fields)}"
            ),
        )
    ensure_workspace_access(db, workspace_id, payload.user_id)
    designation = db.scalar(select(GlobalDesignation).where(
        GlobalDesignation.name == payload.designation.strip(),
    ))
    if designation is None:
        raise HTTPException(status_code=400, detail="Select a valid workspace designation")
    existing = db.scalar(
        select(TeamMember).where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == payload.user_id,
            TeamMember.project_id == payload.project_id,
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="Member is already allocated")
    allocation = TeamMember(
        team_id=team_id,
        user_id=payload.user_id,
        project_id=payload.project_id,
        designation=designation.name,
    )
    db.add(allocation)
    db.commit()
    return db.scalar(
        select(TeamMember)
        .options(
            selectinload(TeamMember.user),
            selectinload(TeamMember.project),
        )
        .where(TeamMember.id == allocation.id)
    )


@router.patch(
    "/{workspace_id}/teams/{team_id}/members/{allocation_id}",
    response_model=TeamMemberRead,
)
def update_team_member_allocation(
    workspace_id: int, team_id: int, allocation_id: int,
    payload: TeamMemberUpdate, db: DB, current_user: CurrentUser,
) -> TeamMember:
    team = require_team_admin(db, team_id, current_user.id)
    if team.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Team not found")
    allocation = db.scalar(select(TeamMember).where(
        TeamMember.id == allocation_id, TeamMember.team_id == team_id
    ))
    if allocation is None:
        raise HTTPException(status_code=404, detail="Team member allocation not found")
    project = db.scalar(select(Project).where(
        Project.id == payload.project_id, Project.workspace_id == workspace_id
    ))
    designation = db.scalar(select(GlobalDesignation).where(
        GlobalDesignation.name == payload.designation.strip(),
    ))
    if project is None:
        raise HTTPException(status_code=400, detail="Select a valid workspace project")
    if designation is None:
        raise HTTPException(status_code=400, detail="Select a valid workspace designation")
    duplicate = db.scalar(select(TeamMember.id).where(
        TeamMember.team_id == team_id,
        TeamMember.user_id == allocation.user_id,
        TeamMember.project_id == project.id,
        TeamMember.id != allocation.id,
    ))
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Member is already allocated to this project")
    allocation.project_id = project.id
    allocation.designation = designation.name
    db.commit()
    return db.scalar(select(TeamMember).options(
        selectinload(TeamMember.user), selectinload(TeamMember.project)
    ).where(TeamMember.id == allocation.id))


@router.delete(
    "/{workspace_id}/teams/{team_id}/members/{allocation_id}", status_code=204
)
def remove_team_member(
    workspace_id: int,
    team_id: int,
    allocation_id: int,
    db: DB,
    current_user: CurrentUser,
) -> None:
    team = require_team_admin(db, team_id, current_user.id)
    if team.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Team not found")
    allocation = db.scalar(
        select(TeamMember).where(
            TeamMember.id == allocation_id, TeamMember.team_id == team_id
        )
    )
    if allocation is None:
        raise HTTPException(status_code=404, detail="Team member not found")
    db.delete(allocation)
    db.commit()
