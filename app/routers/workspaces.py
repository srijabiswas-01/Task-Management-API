from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.dependencies import (
    CurrentUser,
    DB,
    require_workspace_admin,
    require_workspace_member,
    require_team_admin,
)
from app.core.skills import normalize_skills, parse_skills
from app.models import Comment, Department, Designation, Project, Task, Team, TeamManager, TeamMember, User, UserProfile, Workspace, WorkspaceMember, WorkspaceRole
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
    WorkspaceRead,
    WorkspaceUpdate,
)

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])


def validate_team_manager(
    db: DB, workspace_id: int, user_id: int, designation_name: str
) -> None:
    member = db.scalar(select(WorkspaceMember.id).where(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == user_id,
        WorkspaceMember.is_active.is_(True),
    ))
    designation = db.scalar(select(Designation.id).where(
        Designation.workspace_id == workspace_id,
        Designation.name == designation_name.strip(),
    ))
    if member is None:
        raise HTTPException(status_code=400, detail="Team manager must be a workspace member")
    if designation is None:
        raise HTTPException(status_code=400, detail="Select a valid manager designation")


@router.get("/{workspace_id}/departments", response_model=list[DepartmentRead])
def list_departments(workspace_id: int, db: DB, current_user: CurrentUser) -> list[Department]:
    require_workspace_member(db, workspace_id, current_user.id)
    return list(db.scalars(select(Department).where(
        Department.workspace_id == workspace_id
    ).order_by(Department.name)).all())


@router.post("/{workspace_id}/departments", response_model=DepartmentRead, status_code=201)
def create_department(
    workspace_id: int, payload: DepartmentCreate, db: DB, current_user: CurrentUser
) -> Department:
    require_workspace_admin(db, workspace_id, current_user.id)
    name = payload.name.strip()
    if db.scalar(select(Department.id).where(
        Department.workspace_id == workspace_id, Department.name == name
    )):
        raise HTTPException(status_code=409, detail="Department already exists")
    department = Department(workspace_id=workspace_id, name=name, description=payload.description)
    db.add(department); db.commit(); db.refresh(department)
    return department


@router.patch("/{workspace_id}/departments/{department_id}", response_model=DepartmentRead)
def update_department(
    workspace_id: int, department_id: int, payload: DepartmentUpdate,
    db: DB, current_user: CurrentUser
) -> Department:
    require_workspace_admin(db, workspace_id, current_user.id)
    department = db.scalar(select(Department).where(
        Department.id == department_id, Department.workspace_id == workspace_id
    ))
    if department is None:
        raise HTTPException(status_code=404, detail="Department not found")
    values = payload.model_dump(exclude_unset=True)
    old_name = department.name
    if values.get("name") is not None:
        values["name"] = values["name"].strip()
        if db.scalar(select(Department.id).where(
            Department.workspace_id == workspace_id,
            Department.name == values["name"], Department.id != department_id
        )):
            raise HTTPException(status_code=409, detail="Department already exists")
    for field, value in values.items(): setattr(department, field, value)
    if department.name != old_name:
        profiles = db.scalars(select(UserProfile).join(User).join(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            UserProfile.department == old_name,
        )).all()
        for profile in profiles: profile.department = department.name
    db.commit(); db.refresh(department)
    return department


@router.delete("/{workspace_id}/departments/{department_id}", status_code=204)
def delete_department(
    workspace_id: int, department_id: int, db: DB, current_user: CurrentUser
) -> None:
    require_workspace_admin(db, workspace_id, current_user.id)
    department = db.scalar(select(Department).where(
        Department.id == department_id, Department.workspace_id == workspace_id
    ))
    if department is None:
        raise HTTPException(status_code=404, detail="Department not found")
    db.delete(department); db.commit()


@router.get("/{workspace_id}/designations", response_model=list[DesignationRead])
def list_designations(workspace_id: int, db: DB, current_user: CurrentUser) -> list[Designation]:
    require_workspace_member(db, workspace_id, current_user.id)
    return list(db.scalars(select(Designation).where(
        Designation.workspace_id == workspace_id
    ).order_by(Designation.name)).all())


@router.post("/{workspace_id}/designations", response_model=DesignationRead, status_code=201)
def create_designation(
    workspace_id: int, payload: DesignationCreate, db: DB, current_user: CurrentUser
) -> Designation:
    require_workspace_admin(db, workspace_id, current_user.id)
    name = payload.name.strip()
    exists = db.scalar(select(Designation).where(
        Designation.workspace_id == workspace_id, Designation.name == name
    ))
    if exists:
        raise HTTPException(status_code=409, detail="Designation already exists")
    designation = Designation(workspace_id=workspace_id, name=name, description=payload.description)
    db.add(designation); db.commit(); db.refresh(designation)
    return designation


@router.patch("/{workspace_id}/designations/{designation_id}", response_model=DesignationRead)
def update_designation(
    workspace_id: int, designation_id: int, payload: DesignationUpdate,
    db: DB, current_user: CurrentUser
) -> Designation:
    require_workspace_admin(db, workspace_id, current_user.id)
    designation = db.scalar(select(Designation).where(
        Designation.id == designation_id, Designation.workspace_id == workspace_id
    ))
    if designation is None:
        raise HTTPException(status_code=404, detail="Designation not found")
    values = payload.model_dump(exclude_unset=True)
    old_name = designation.name
    if values.get("name") is not None:
        values["name"] = values["name"].strip()
        duplicate = db.scalar(select(Designation.id).where(
            Designation.workspace_id == workspace_id,
            Designation.name == values["name"], Designation.id != designation_id
        ))
        if duplicate:
            raise HTTPException(status_code=409, detail="Designation already exists")
    for field, value in values.items(): setattr(designation, field, value)
    if designation.name != old_name:
        allocations = db.scalars(select(TeamMember).join(Team).where(
            Team.workspace_id == workspace_id, TeamMember.designation == old_name
        )).all()
        for allocation in allocations: allocation.designation = designation.name
        managers = db.scalars(select(TeamManager).join(Team).where(
            Team.workspace_id == workspace_id, TeamManager.designation == old_name
        )).all()
        for manager in managers: manager.designation = designation.name
        profiles = db.scalars(select(UserProfile).join(User).join(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            UserProfile.professional_title == old_name,
        )).all()
        for profile in profiles: profile.professional_title = designation.name
    db.commit(); db.refresh(designation)
    return designation


@router.delete("/{workspace_id}/designations/{designation_id}", status_code=204)
def delete_designation(
    workspace_id: int, designation_id: int, db: DB, current_user: CurrentUser
) -> None:
    require_workspace_admin(db, workspace_id, current_user.id)
    designation = db.scalar(select(Designation).where(
        Designation.id == designation_id, Designation.workspace_id == workspace_id
    ))
    if designation is None:
        raise HTTPException(status_code=404, detail="Designation not found")
    db.delete(designation); db.commit()


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
def list_workspaces(db: DB, current_user: CurrentUser) -> list[Workspace]:
    return list(
        db.scalars(
            select(Workspace)
            .join(WorkspaceMember)
            .where(
                WorkspaceMember.user_id == current_user.id,
                WorkspaceMember.is_active.is_(True),
            )
            .order_by(Workspace.created_at.desc())
        ).all()
    )


@router.delete("/{workspace_id}", status_code=204)
def delete_workspace(
    workspace_id: int, db: DB, current_user: CurrentUser
) -> None:
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if workspace.owner_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Only the workspace owner can delete this workspace",
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
    require_workspace_member(db, workspace_id, current_user.id)
    return list(
        db.scalars(
            select(WorkspaceMember)
            .options(selectinload(WorkspaceMember.user).selectinload(User.profile))
            .where(WorkspaceMember.workspace_id == workspace_id)
        ).all()
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
    ) for user in users]


@router.get("/{workspace_id}/skill-catalog", response_model=list[str])
def skill_catalog(
    workspace_id: int, db: DB, current_user: CurrentUser
) -> list[str]:
    require_workspace_member(db, workspace_id, current_user.id)
    values = db.scalars(
        select(UserProfile.skills).join(User).join(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.is_active.is_(True),
        )
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
    members = db.scalars(select(WorkspaceMember).options(
        selectinload(WorkspaceMember.user).selectinload(User.profile)
    ).where(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.is_active.is_(True),
    ).order_by(WorkspaceMember.created_at)).all()
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
    return [SkillMemberRead(
        user_id=member.user_id,
        name=member.user.name,
        email=member.user.email,
        professional_title=member.professional_title,
        department=member.department,
        profile_image=member.user.profile.profile_image if member.user.profile else None,
        skills=parse_skills(member.user.profile.skills if member.user.profile else None),
        project_ids=all_project_ids if member.role == WorkspaceRole.admin else projects_by_user.get(member.user_id, []),
    ) for member in members]


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
    if payload.professional_title and db.scalar(select(Designation.id).where(
        Designation.workspace_id == workspace_id,
        Designation.name == payload.professional_title,
    )) is None:
        raise HTTPException(status_code=400, detail="Select a valid designation")
    if payload.department and db.scalar(select(Department.id).where(
        Department.workspace_id == workspace_id,
        Department.name == payload.department,
    )) is None:
        raise HTTPException(status_code=400, detail="Select a valid department")
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
    )


def update_admin_managed_profile(
    db: DB, workspace_id: int, user: User, payload: UserProfileUpdate
) -> UserProfileRead:
    if payload.professional_title and db.scalar(select(Designation.id).where(
        Designation.workspace_id == workspace_id,
        Designation.name == payload.professional_title,
    )) is None:
        raise HTTPException(status_code=400, detail="Select a valid designation")
    if payload.department and db.scalar(select(Department.id).where(
        Department.workspace_id == workspace_id,
        Department.name == payload.department,
    )) is None:
        raise HTTPException(status_code=400, detail="Select a valid department")
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
    if payload.professional_title and db.scalar(select(Designation.id).where(
        Designation.workspace_id == workspace_id,
        Designation.name == payload.professional_title,
    )) is None:
        raise HTTPException(status_code=400, detail="Select a valid designation")
    if payload.department and db.scalar(select(Department.id).where(
        Department.workspace_id == workspace_id,
        Department.name == payload.department,
    )) is None:
        raise HTTPException(status_code=400, detail="Select a valid department")
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
    require_workspace_member(db, workspace_id, current_user.id)
    return list(
        db.scalars(
            select(Team).options(
                selectinload(Team.manager_record).selectinload(TeamManager.user)
            )
            .where(Team.workspace_id == workspace_id)
            .order_by(Team.created_at.desc())
        ).all()
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
    require_workspace_member(db, workspace_id, current_user.id)
    return list(
        db.scalars(
            select(TeamMember)
            .join(Team)
            .options(
                selectinload(TeamMember.user),
                selectinload(TeamMember.project),
            )
            .where(Team.workspace_id == workspace_id)
            .order_by(TeamMember.created_at)
        ).all()
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
    member = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == payload.user_id,
            WorkspaceMember.is_active.is_(True),
        )
    )
    project = db.scalar(
        select(Project).where(
            Project.id == payload.project_id,
            Project.workspace_id == workspace_id,
        )
    )
    if member is None or project is None:
        raise HTTPException(status_code=400, detail="Invalid member or project")
    designation = db.scalar(select(Designation).where(
        Designation.workspace_id == workspace_id,
        Designation.name == payload.designation.strip(),
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
    designation = db.scalar(select(Designation).where(
        Designation.workspace_id == workspace_id,
        Designation.name == payload.designation.strip(),
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
