"""Skill Taxonomy, Prerequisite DAG, and Target Role Registry."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Sequence

from lyra.learning.models import Skill, SkillLevel, TargetRole
from lyra.observability.logging import get_logger

logger = get_logger("learning.skill_engine")


def _seed_skills() -> list[Skill]:
    """Provide a robust standard taxonomy of skills spanning modern software engineering and AI."""
    return [
        # Foundations & Protocols
        Skill(
            id="http_basics",
            name="HTTP Basics",
            category="Web Development",
            prerequisites=[],
            related_skills=["REST APIs", "Web Security"],
            difficulty=SkillLevel.BEGINNER,
            description="HTTP request/response cycle, verbs (GET, POST, PUT, DELETE), headers, and status codes.",
        ),
        Skill(
            id="git_basics",
            name="Git Basics",
            category="Tools",
            prerequisites=[],
            related_skills=["GitHub", "CI/CD"],
            difficulty=SkillLevel.BEGINNER,
            description="Version control, branching, committing, merging, and remote collaboration.",
        ),
        # Programming
        Skill(
            id="python_fundamentals",
            name="Python Fundamentals",
            category="Programming",
            prerequisites=[],
            related_skills=["Data Structures", "OOP"],
            difficulty=SkillLevel.BEGINNER,
            description="Python syntax, variables, data structures (lists, dicts), control flow, and functions.",
        ),
        Skill(
            id="javascript_fundamentals",
            name="JavaScript Fundamentals",
            category="Programming",
            prerequisites=[],
            related_skills=["TypeScript", "Node.js"],
            difficulty=SkillLevel.BEGINNER,
            description="Modern ES6+ JavaScript, closures, event loop, promises, and async/await.",
        ),
        Skill(
            id="typescript",
            name="TypeScript",
            category="Programming",
            prerequisites=["JavaScript Fundamentals"],
            related_skills=["JavaScript Fundamentals", "React"],
            difficulty=SkillLevel.INTERMEDIATE,
            description="Static typing, interfaces, generics, type narrowing, and compiler configuration.",
        ),
        # Backend & APIs
        Skill(
            id="rest_apis",
            name="REST APIs",
            category="Backend",
            prerequisites=["HTTP Basics"],
            related_skills=["FastAPI / Express", "API Authentication", "System Design"],
            difficulty=SkillLevel.ELEMENTARY,
            description="Designing scalable, semantic RESTful web APIs and payload validation.",
        ),
        Skill(
            id="nodejs_routes",
            name="Node.js & Express Routing",
            category="Backend",
            prerequisites=["JavaScript Fundamentals", "REST APIs"],
            related_skills=["Node.js", "Express", "REST APIs"],
            difficulty=SkillLevel.INTERMEDIATE,
            description="Building backend servers, middleware pipelines, routing, and controller architectures in Node.js.",
        ),
        Skill(
            id="fastapi_backend",
            name="FastAPI & Python Web Services",
            category="Backend",
            prerequisites=["Python Fundamentals", "REST APIs"],
            related_skills=["Pydantic", "AsyncIO", "REST APIs"],
            difficulty=SkillLevel.INTERMEDIATE,
            description="High-performance async Python backend development using FastAPI and Pydantic.",
        ),
        Skill(
            id="api_authentication",
            name="API Authentication & Security",
            category="Backend",
            prerequisites=["REST APIs"],
            related_skills=["OAuth2", "JWT", "Cybersecurity"],
            difficulty=SkillLevel.INTERMEDIATE,
            description="Authentication vs Authorization, JWT tokens, sessions, hashing, and role-based access control.",
        ),
        # Databases
        Skill(
            id="sql_fundamentals",
            name="SQL Fundamentals",
            category="Databases",
            prerequisites=[],
            related_skills=["PostgreSQL", "Relational Databases"],
            difficulty=SkillLevel.BEGINNER,
            description="Relational database concepts, schema definition (DDL), and standard CRUD queries (SELECT, INSERT, UPDATE, DELETE).",
        ),
        Skill(
            id="sql_joins",
            name="SQL Joins & Relational Queries",
            category="Databases",
            prerequisites=["SQL Fundamentals"],
            related_skills=["Query Optimization", "PostgreSQL"],
            difficulty=SkillLevel.ELEMENTARY,
            description="Combining tables with INNER JOIN, LEFT/RIGHT JOIN, FULL OUTER JOIN, GROUP BY, and aggregations.",
        ),
        Skill(
            id="database_indexing_optimization",
            name="Database Indexing & Optimization",
            category="Databases",
            prerequisites=["SQL Joins & Relational Queries"],
            related_skills=["System Design", "PostgreSQL"],
            difficulty=SkillLevel.INTERMEDIATE,
            description="B-trees, query execution plans (EXPLAIN), connection pooling, migrations, and transactions (ACID).",
        ),
        Skill(
            id="mongodb_crud",
            name="MongoDB & Document Stores",
            category="Databases",
            prerequisites=[],
            related_skills=["NoSQL", "Mongoose"],
            difficulty=SkillLevel.BEGINNER,
            description="Document-oriented database schema design, indexing, and aggregation pipelines.",
        ),
        # Testing & Quality
        Skill(
            id="automated_testing",
            name="Automated Testing & TDD",
            category="Backend",
            prerequisites=["REST APIs"],
            related_skills=["pytest", "Jest", "CI/CD"],
            difficulty=SkillLevel.INTERMEDIATE,
            description="Unit testing, integration testing, mocking external dependencies, test-driven development, and coverage.",
        ),
        # DevOps & Deployment
        Skill(
            id="docker_containers",
            name="Docker & Containerization",
            category="DevOps",
            prerequisites=["Git Basics"],
            related_skills=["Kubernetes", "Cloud Deployment"],
            difficulty=SkillLevel.INTERMEDIATE,
            description="Containerizing applications, multi-stage Dockerfiles, compose setups, and container isolation.",
        ),
        Skill(
            id="cloud_deployment",
            name="Cloud Deployment & CI/CD",
            category="Cloud",
            prerequisites=["Docker & Containerization", "REST APIs"],
            related_skills=["AWS", "GCP", "GitHub Actions"],
            difficulty=SkillLevel.INTERMEDIATE,
            description="Automated continuous integration, deployment pipelines, reverse proxies, and cloud hosting.",
        ),
        # AI & Machine Learning
        Skill(
            id="ml_fundamentals",
            name="Machine Learning Fundamentals",
            category="Machine Learning",
            prerequisites=["Python Fundamentals"],
            related_skills=["Statistics", "Scikit-Learn"],
            difficulty=SkillLevel.INTERMEDIATE,
            description="Supervised vs unsupervised learning, regression, classification, metrics (accuracy, precision, recall, F1).",
        ),
        Skill(
            id="deep_learning",
            name="Deep Learning & Neural Networks",
            category="AI",
            prerequisites=["Machine Learning Fundamentals"],
            related_skills=["PyTorch", "Transformers"],
            difficulty=SkillLevel.ADVANCED,
            description="Backpropagation, neural architectures, activation functions, regularization, and model training in PyTorch.",
        ),
        Skill(
            id="llm_engineering",
            name="LLM Application Engineering",
            category="AI",
            prerequisites=["Python Fundamentals", "REST APIs"],
            related_skills=["Prompt Engineering", "RAG", "LangChain"],
            difficulty=SkillLevel.INTERMEDIATE,
            description="API-based LLM integration, structured JSON outputs, function calling, tool use, and latency optimization.",
        ),
        Skill(
            id="rag_and_vector_dbs",
            name="RAG & Vector Search",
            category="AI",
            prerequisites=["LLM Application Engineering"],
            related_skills=["Chroma", "Embeddings", "Information Retrieval"],
            difficulty=SkillLevel.ADVANCED,
            description="Chunking strategies, dense embeddings, vector indexing, retrieval-augmented generation, and semantic reranking.",
        ),
        # System Design
        Skill(
            id="system_design",
            name="System Design & Architecture",
            category="System Design",
            prerequisites=["REST APIs", "Database Indexing & Optimization"],
            related_skills=["Caching", "Message Queues", "Microservices"],
            difficulty=SkillLevel.ADVANCED,
            description="Designing scalable distributed architectures, caching strategies, rate limiting, and asynchronous message queues.",
        ),
    ]


def _seed_roles() -> list[TargetRole]:
    """Provide standard target career roles with dependency blueprints."""
    return [
        TargetRole(
            role_name="Backend Developer",
            required_skills={
                "HTTP Basics": SkillLevel.INTERMEDIATE,
                "REST APIs": SkillLevel.INTERMEDIATE,
                "SQL Fundamentals": SkillLevel.INTERMEDIATE,
                "SQL Joins & Relational Queries": SkillLevel.INTERMEDIATE,
                "API Authentication & Security": SkillLevel.INTERMEDIATE,
                "Automated Testing & TDD": SkillLevel.ELEMENTARY,
                "Git Basics": SkillLevel.ELEMENTARY,
            },
            preferred_skills={
                "Database Indexing & Optimization": SkillLevel.INTERMEDIATE,
                "Docker & Containerization": SkillLevel.INTERMEDIATE,
                "Cloud Deployment & CI/CD": SkillLevel.INTERMEDIATE,
                "System Design & Architecture": SkillLevel.ELEMENTARY,
            },
            typical_tasks=[
                "Build and document robust RESTful APIs",
                "Design normalized relational database schemas and optimize queries",
                "Implement secure token-based user authentication and RBAC",
                "Write comprehensive automated unit and integration tests",
                "Containerize and deploy services to cloud environments",
            ],
            learning_dependencies={
                "REST APIs": ["HTTP Basics"],
                "SQL Joins & Relational Queries": ["SQL Fundamentals"],
                "Database Indexing & Optimization": ["SQL Joins & Relational Queries"],
                "API Authentication & Security": ["REST APIs"],
                "Automated Testing & TDD": ["REST APIs"],
                "System Design & Architecture": ["REST APIs", "Database Indexing & Optimization"],
            },
            description="Engineers scalable server-side systems, API contracts, databases, and microservices.",
        ),
        TargetRole(
            role_name="AI Engineer",
            required_skills={
                "Python Fundamentals": SkillLevel.ADVANCED,
                "HTTP Basics": SkillLevel.ELEMENTARY,
                "REST APIs": SkillLevel.INTERMEDIATE,
                "Machine Learning Fundamentals": SkillLevel.INTERMEDIATE,
                "LLM Application Engineering": SkillLevel.INTERMEDIATE,
                "RAG & Vector Search": SkillLevel.INTERMEDIATE,
                "Git Basics": SkillLevel.ELEMENTARY,
            },
            preferred_skills={
                "Deep Learning & Neural Networks": SkillLevel.INTERMEDIATE,
                "Docker & Containerization": SkillLevel.ELEMENTARY,
                "Automated Testing & TDD": SkillLevel.ELEMENTARY,
            },
            typical_tasks=[
                "Integrate multimodal foundation models into production services",
                "Design and evaluate robust RAG knowledge retrieval pipelines",
                "Fine-tune and prompt-engineer models for structured outputs",
                "Deploy and optimize real-time AI inference endpoints",
            ],
            learning_dependencies={
                "REST APIs": ["HTTP Basics"],
                "Machine Learning Fundamentals": ["Python Fundamentals"],
                "LLM Application Engineering": ["Python Fundamentals", "REST APIs"],
                "RAG & Vector Search": ["LLM Application Engineering"],
                "Deep Learning & Neural Networks": ["Machine Learning Fundamentals"],
            },
            description="Builds production AI systems, LLM workflows, RAG architectures, and model deployment pipelines.",
        ),
        TargetRole(
            role_name="Fullstack Developer",
            required_skills={
                "JavaScript Fundamentals": SkillLevel.INTERMEDIATE,
                "HTTP Basics": SkillLevel.INTERMEDIATE,
                "REST APIs": SkillLevel.INTERMEDIATE,
                "SQL Fundamentals": SkillLevel.ELEMENTARY,
                "Git Basics": SkillLevel.ELEMENTARY,
            },
            preferred_skills={
                "TypeScript": SkillLevel.INTERMEDIATE,
                "Docker & Containerization": SkillLevel.ELEMENTARY,
                "Cloud Deployment & CI/CD": SkillLevel.ELEMENTARY,
            },
            typical_tasks=[
                "Develop responsive web interfaces and user experiences",
                "Build server-side logic and database operations",
                "Connect frontend components to REST APIs",
            ],
            learning_dependencies={
                "REST APIs": ["HTTP Basics"],
                "TypeScript": ["JavaScript Fundamentals"],
            },
            description="Builds end-to-end web applications across frontend clients and backend services.",
        ),
    ]


class SkillEngine:
    """Manages skill taxonomy, dependency graphs, and role matching."""

    def __init__(self, repository: Any | None = None) -> None:
        self.repository = repository
        self._skills: dict[str, Skill] = {}
        self._roles: dict[str, TargetRole] = {}
        self._load_seeds()

    def _load_seeds(self) -> None:
        """Seed initial taxonomy and roles, merging with any existing in DB."""
        for s in _seed_skills():
            self._skills[s.name.lower()] = s
        for r in _seed_roles():
            self._roles[r.role_name.lower()] = r

        if self.repository:
            try:
                for db_s in self.repository.list_skills():
                    self._skills[db_s.name.lower()] = db_s
                for db_r in self.repository.list_target_roles():
                    self._roles[db_r.role_name.lower()] = db_r
            except Exception as e:
                logger.warning("Could not load skills/roles from repo: %s", e)

    def register_skill(self, skill: Skill) -> None:
        self._skills[skill.name.lower()] = skill
        if self.repository:
            try:
                self.repository.save_skill(skill)
            except Exception as e:
                logger.warning("Failed to persist skill %s: %s", skill.name, e)

    def register_target_role(self, role: TargetRole) -> None:
        self._roles[role.role_name.lower()] = role
        if self.repository:
            try:
                self.repository.save_target_role(role)
            except Exception as e:
                logger.warning("Failed to persist role %s: %s", role.role_name, e)

    def get_skill(self, skill_name: str) -> Skill | None:
        norm = skill_name.strip().lower()
        if norm in self._skills:
            return self._skills[norm]
        # Partial match
        for k, v in self._skills.items():
            if norm in k or k in norm:
                return v
        return None

    def list_skills(self) -> list[Skill]:
        return list(self._skills.values())

    def get_target_role(self, role_name: str) -> TargetRole | None:
        norm = role_name.strip().lower()
        if norm in self._roles:
            return self._roles[norm]
        for k, v in self._roles.items():
            if norm in k or k in norm:
                return v
        return None

    def list_target_roles(self) -> list[TargetRole]:
        return list(self._roles.values())

    def topological_sort(self, skill_names: Sequence[str]) -> list[str]:
        """Return the given skills ordered by prerequisite dependencies first.

        If Skill B depends on Skill A, Skill A is guaranteed to appear before Skill B.
        """
        requested = {s.strip() for s in skill_names if s.strip()}
        if not requested:
            return []

        # Graph of dependencies within requested skills
        adj: dict[str, list[str]] = defaultdict(list)
        in_degree: dict[str, int] = {s: 0 for s in requested}

        for s_name in requested:
            skill_obj = self.get_skill(s_name)
            if not skill_obj:
                continue
            for prereq in skill_obj.prerequisites:
                # Find if prereq or a matching skill is in requested
                matching = next((r for r in requested if r.lower() == prereq.lower() or prereq.lower() in r.lower()), None)
                if matching and matching != s_name:
                    adj[matching].append(s_name)
                    in_degree[s_name] += 1

        queue: deque[str] = deque([s for s in requested if in_degree[s] == 0])
        ordered: list[str] = []

        while queue:
            curr = queue.popleft()
            ordered.append(curr)
            for nxt in adj[curr]:
                in_degree[nxt] -= 1
                if in_degree[nxt] == 0:
                    queue.append(nxt)

        # Append any remaining (in case of cycles or unvisited nodes)
        for s in requested:
            if s not in ordered:
                ordered.append(s)

        return ordered
