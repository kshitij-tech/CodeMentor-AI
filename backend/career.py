from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RoleProfile:
    key: str
    name: str
    category: str
    summary: str
    dsa_topics: tuple[str, ...]
    cs_fundamentals: tuple[str, ...]
    role_skills: tuple[str, ...]
    interview_focus: tuple[str, ...]
    company_categories: tuple[str, ...]
    phases: tuple[dict[str, Any], ...]


ROLE_PROFILES: dict[str, RoleProfile] = {
    "software_engineer": RoleProfile(
        "software_engineer",
        "Software Engineer",
        "Engineering",
        "Balanced DSA, CS fundamentals, software engineering and interview readiness.",
        ("Arrays & Strings", "Hashing & Hash Maps", "Binary Search", "Trees & BST", "Graphs (BFS/DFS)", "Dynamic Programming"),
        ("OOP", "DBMS", "Operating Systems", "Computer Networks", "System Design", "Software Engineering"),
        ("Python/Java/C++", "Git", "Testing", "REST APIs", "Debugging"),
        ("DSA", "CS fundamentals", "Coding design", "Behavioral"),
        ("Big Tech", "Product/SaaS", "Startups"),
        (
            {"id": "foundations", "title": "Build foundations", "weeks": 2, "items": ["OOP", "DBMS", "Operating Systems", "Computer Networks"]},
            {"id": "dsa", "title": "Sharpen DSA", "weeks": 4, "items": ["Arrays & Strings", "Hashing & Hash Maps", "Trees & BST", "Graphs (BFS/DFS)", "Dynamic Programming"]},
            {"id": "interviews", "title": "Interview simulation", "weeks": 2, "items": ["System Design", "Software Engineering", "Testing", "Git"]},
        ),
    ),
    "backend_developer": RoleProfile(
        "backend_developer", "Backend Developer", "Engineering",
        "Backend-focused preparation across APIs, databases, systems and production design.",
        ("Arrays & Strings", "Hashing & Hash Maps", "Binary Search", "Trees & BST", "Graphs (BFS/DFS)"),
        ("OOP", "DBMS", "Operating Systems", "Computer Networks", "System Design", "Distributed Systems"),
        ("Python/FastAPI/Django", "REST APIs", "SQL", "Caching", "Authentication", "Testing", "Docker"),
        ("API design", "Databases", "System design", "Debugging", "Behavioral"),
        ("Product/SaaS", "FinTech", "Big Tech", "Startups"),
        (
            {"id": "backend-foundations", "title": "Backend foundations", "weeks": 2, "items": ["DBMS", "Computer Networks", "OOP", "REST APIs"]},
            {"id": "systems", "title": "Production systems", "weeks": 3, "items": ["Caching", "Authentication", "Distributed Systems", "Docker"]},
            {"id": "backend-interviews", "title": "Backend interviews", "weeks": 3, "items": ["SQL", "REST APIs", "System Design", "Docker"]},
        ),
    ),
    "frontend_developer": RoleProfile(
        "frontend_developer", "Frontend Developer", "Engineering",
        "Frontend interviews with DSA fundamentals, browser concepts, UI architecture and JavaScript depth.",
        ("Arrays & Strings", "Hashing & Hash Maps", "Sorting", "Two Pointers", "Stacks & Queues"),
        ("OOP", "Computer Networks", "Operating Systems", "System Design", "Web Fundamentals"),
        ("JavaScript/TypeScript", "React", "Accessibility", "Browser APIs", "State Management", "Testing", "Performance"),
        ("JavaScript", "React architecture", "Web performance", "UI debugging", "Behavioral"),
        ("Product/SaaS", "Big Tech", "Startups"),
        (
            {"id": "web-foundations", "title": "Web foundations", "weeks": 2, "items": ["JavaScript/TypeScript", "Computer Networks", "Browser APIs", "Accessibility"]},
            {"id": "frontend-systems", "title": "Frontend systems", "weeks": 3, "items": ["React", "State Management", "Performance", "Testing"]},
            {"id": "frontend-interviews", "title": "Frontend interviews", "weeks": 2, "items": ["JavaScript/TypeScript", "React", "Performance", "Testing"]},
        ),
    ),
    "full_stack_developer": RoleProfile(
        "full_stack_developer", "Full Stack Developer", "Engineering",
        "End-to-end preparation spanning frontend, backend, data and deployment.",
        ("Arrays & Strings", "Hashing & Hash Maps", "Sorting", "Trees & BST", "Graphs (BFS/DFS)"),
        ("OOP", "DBMS", "Operating Systems", "Computer Networks", "System Design", "Web Fundamentals"),
        ("JavaScript/TypeScript", "React", "Python/FastAPI/Django", "SQL", "REST APIs", "Docker", "Testing", "Git", "Debugging"),
        ("Full-stack architecture", "APIs", "Databases", "Frontend", "Behavioral"),
        ("Product/SaaS", "Startups", "Big Tech"),
        (
            {"id": "fullstack-foundations", "title": "Full-stack foundations", "weeks": 3, "items": ["JavaScript/TypeScript", "Python/FastAPI/Django", "SQL", "Computer Networks"]},
            {"id": "integration", "title": "Build integrated systems", "weeks": 3, "items": ["React", "REST APIs", "Authentication", "Docker"]},
            {"id": "fullstack-interviews", "title": "Full-stack interviews", "weeks": 2, "items": ["System Design", "Debugging", "Testing", "Docker"]},
        ),
    ),
    "data_ml": RoleProfile(
        "data_ml", "Data / ML Engineer", "Data & AI",
        "Data structures plus statistics, ML fundamentals, pipelines and applied model reasoning.",
        ("Arrays & Strings", "Hashing & Hash Maps", "Sorting", "Binary Search", "Graphs (BFS/DFS)"),
        ("OOP", "DBMS", "Operating Systems", "Computer Networks", "Statistics", "Machine Learning", "System Design"),
        ("Python", "SQL", "Pandas/NumPy", "Machine Learning", "Model Evaluation", "Data Pipelines", "Supervised Learning", "Feature Engineering", "Pipelines", "Docker"),
        ("ML theory", "SQL", "Data reasoning", "ML system design", "Behavioral"),
        ("Big Tech", "FinTech", "Product/SaaS", "Research/AI"),
        (
            {"id": "data-foundations", "title": "Data foundations", "weeks": 3, "items": ["Python", "SQL", "Statistics", "DBMS"]},
            {"id": "ml-core", "title": "ML core", "weeks": 4, "items": ["Supervised Learning", "Model Evaluation", "Feature Engineering", "Pipelines"]},
            {"id": "ml-interviews", "title": "ML interviews", "weeks": 2, "items": ["Machine Learning", "Model Evaluation", "Data Pipelines", "Docker"]},
        ),
    ),
    "devops_engineer": RoleProfile(
        "devops_engineer", "DevOps / Cloud Engineer", "Infrastructure",
        "Infrastructure, networking, automation, reliability and production troubleshooting preparation.",
        ("Arrays & Strings", "Hashing & Hash Maps", "Binary Search", "Graphs (BFS/DFS)"),
        ("Operating Systems", "Computer Networks", "DBMS", "System Design", "Distributed Systems", "Security Fundamentals"),
        ("Linux", "Docker", "CI/CD", "Cloud", "Kubernetes", "Observability", "Infrastructure as Code", "Troubleshooting", "Incident Response"),
        ("Networking", "Troubleshooting", "System design", "Incident response", "Behavioral"),
        ("Big Tech", "Product/SaaS", "FinTech", "Startups"),
        (
            {"id": "infra-foundations", "title": "Infrastructure foundations", "weeks": 3, "items": ["Linux", "Computer Networks", "Operating Systems", "Docker"]},
            {"id": "platform", "title": "Platform engineering", "weeks": 3, "items": ["Cloud", "CI/CD", "Kubernetes", "Observability"]},
            {"id": "devops-interviews", "title": "Reliability interviews", "weeks": 2, "items": ["Troubleshooting", "System Design", "Incident Response", "Observability"]},
        ),
    ),
    "mobile_developer": RoleProfile(
        "mobile_developer", "Mobile Developer", "Application Engineering",
        "Mobile architecture, platform fundamentals, app performance and coding interviews.",
        ("Arrays & Strings", "Hashing & Hash Maps", "Sorting", "Trees & BST", "Graphs (BFS/DFS)"),
        ("OOP", "DBMS", "Operating Systems", "Computer Networks", "System Design", "Mobile Fundamentals"),
        ("Flutter/React Native", "Android/iOS fundamentals", "REST APIs", "State Management", "Testing", "Performance", "Platform fundamentals", "App architecture"),
        ("Mobile architecture", "UI state", "Networking", "Performance", "Behavioral"),
        ("Product/SaaS", "Big Tech", "Startups"),
        (
            {"id": "mobile-foundations", "title": "Mobile foundations", "weeks": 3, "items": ["OOP", "Computer Networks", "State Management", "REST APIs"]},
            {"id": "app-architecture", "title": "App architecture", "weeks": 3, "items": ["Platform fundamentals", "Testing", "Performance", "App architecture"]},
            {"id": "mobile-interviews", "title": "Mobile interviews", "weeks": 2, "items": ["Flutter/React Native", "State Management", "Performance", "Testing"]},
        ),
    ),
}

CS_FUNDAMENTALS = (
    "DBMS", "Operating Systems", "Computer Networks", "OOP", "System Design",
    "Software Engineering", "Distributed Systems", "Web Fundamentals", "Statistics",
    "Machine Learning", "Security Fundamentals", "Mobile Fundamentals",
)

COMPANY_CATEGORIES: dict[str, dict[str, Any]] = {
    "Big Tech": {"description": "Large product companies with structured technical loops.", "companies": ["Google", "Microsoft", "Amazon", "Meta", "Apple"], "focus": ["DSA", "CS fundamentals", "System design", "Behavioral"]},
    "Product/SaaS": {"description": "Product companies emphasizing practical engineering and ownership.", "companies": ["Atlassian", "Adobe", "Salesforce", "ServiceNow", "HubSpot"], "focus": ["Problem solving", "Role depth", "System design", "Behavioral"]},
    "FinTech": {"description": "Financial technology roles with strong correctness, data and systems expectations.", "companies": ["Razorpay", "PhonePe", "PayPal", "Walmart Global Tech", "JPMorgan Chase"], "focus": ["DSA", "DBMS", "APIs", "Systems", "Behavioral"]},
    "Startups": {"description": "High-ownership environments with broad role scope.", "companies": ["Early-stage startups", "Growth-stage startups", "Developer tools startups"], "focus": ["Practical coding", "Architecture", "Debugging", "Ownership"]},
    "Research/AI": {"description": "AI and research-oriented teams with deeper ML and experimentation interviews.", "companies": ["AI labs", "Applied AI teams", "Research engineering teams"], "focus": ["ML fundamentals", "Statistics", "Python", "ML systems"]},
}


def _q(
    question_id: str,
    prompt: str,
    kind: str,
    difficulty: str,
    roles: tuple[str, ...],
    topics: tuple[str, ...],
    rubric: tuple[str, ...],
    companies: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "id": question_id,
        "prompt": prompt,
        "type": kind,
        "difficulty": difficulty,
        "roles": roles,
        "topics": topics,
        "rubric": rubric,
        "companies": companies,
    }


INTERVIEW_QUESTIONS = (
    _q("tech-two-sum", "How would you solve Two Sum, and what is the time and space complexity?", "technical", "Easy", tuple(ROLE_PROFILES), ("Arrays & Strings", "Hashing & Hash Maps"), ("hash map", "O(n)", "complement"), ("Google", "Microsoft", "Amazon", "Meta", "Apple")),
    _q("tech-binary-search", "Explain binary search and the invariants you maintain while implementing it.", "technical", "Easy", tuple(ROLE_PROFILES), ("Binary Search",), ("sorted", "mid", "invariant", "O(log"), ("Google", "Microsoft", "Amazon", "Meta")),
    _q("tech-process-thread", "What is the difference between a process and a thread, and when would you choose one over the other?", "technical", "Medium", tuple(ROLE_PROFILES), ("Operating Systems",), ("address space", "shared memory", "context switch")),
    _q("tech-acid", "Explain ACID properties and give a practical example where each matters.", "technical", "Medium", tuple(ROLE_PROFILES), ("DBMS",), ("atomicity", "consistency", "isolation", "durability")),
    _q("tech-http", "Walk through what happens when a browser makes an HTTPS request to an API.", "technical", "Medium", tuple(ROLE_PROFILES), ("Computer Networks", "Web Fundamentals"), ("DNS", "TLS", "HTTP", "TCP")),
    _q("tech-oop", "Explain encapsulation, abstraction, inheritance and polymorphism using a software example.", "technical", "Easy", tuple(ROLE_PROFILES), ("OOP",), ("encapsulation", "abstraction", "inheritance", "polymorphism")),
    _q("tech-cache", "Design a cache for a read-heavy backend service. What eviction strategy and invalidation approach would you use?", "technical", "Hard", ("backend_developer", "full_stack_developer", "software_engineer", "devops_engineer"), ("System Design",), ("cache", "TTL", "invalidation", "LRU", "consistency")),
    _q("tech-api", "How would you design a REST API for a multi-tenant task management service?", "technical", "Hard", ("backend_developer", "full_stack_developer", "software_engineer"), ("REST APIs", "System Design"), ("resource", "authentication", "authorization", "pagination", "versioning"), ("Atlassian", "Salesforce", "Razorpay", "PhonePe")),
    _q("tech-react", "How does React state flow work, and how would you prevent unnecessary re-renders in a large application?", "technical", "Medium", ("frontend_developer", "full_stack_developer"), ("React",), ("state", "props", "memoization", "component", "render"), ("Google", "Meta", "Microsoft", "Atlassian")),
    _q("tech-js-event-loop", "Explain the JavaScript event loop, promises and microtasks in a practical example.", "technical", "Medium", ("frontend_developer", "full_stack_developer"), ("JavaScript/TypeScript",), ("call stack", "event loop", "microtask", "promise")),
    _q("tech-sql", "How would you diagnose and optimize a slow SQL query on a production table?", "technical", "Hard", ("backend_developer", "full_stack_developer", "data_ml"), ("DBMS", "SQL"), ("explain", "index", "query plan", "cardinality"), ("Amazon", "Microsoft", "Razorpay", "PhonePe", "JPMorgan Chase")),
    _q("tech-ml-overfit", "What is overfitting, how can you detect it, and what techniques reduce it?", "technical", "Medium", ("data_ml",), ("Machine Learning",), ("validation", "regularization", "cross-validation", "generalization"), ("Google", "Microsoft", "Amazon", "AI labs")),
    _q("tech-ml-metrics", "How would you choose between precision, recall, F1, ROC-AUC and PR-AUC for an imbalanced classifier?", "technical", "Hard", ("data_ml",), ("Machine Learning", "Statistics"), ("imbalance", "precision", "recall", "PR-AUC", "threshold")),
    _q("tech-pipeline", "Design a reliable data/ML pipeline from raw events to an online prediction service.", "technical", "Hard", ("data_ml",), ("Data Pipelines", "System Design"), ("ingestion", "validation", "feature", "deployment", "monitoring")),
    _q("tech-docker", "Why use containers, and what are the most important concerns when running services in Docker in production?", "technical", "Medium", ("backend_developer", "full_stack_developer", "devops_engineer", "data_ml"), ("Docker",), ("image", "isolation", "resources", "secrets", "health"), ("Amazon", "Microsoft", "Atlassian")),
    _q("tech-kubernetes", "What problem does Kubernetes solve, and what would you inspect first when a deployment keeps restarting?", "technical", "Hard", ("devops_engineer",), ("Kubernetes",), ("pod", "logs", "probe", "resources", "events")),
    _q("tech-mobile-offline", "How would you design a mobile app to remain useful when the network is unavailable?", "technical", "Medium", ("mobile_developer",), ("Mobile Fundamentals", "State Management"), ("local cache", "sync", "conflict", "retry")),
    _q("tech-mobile-performance", "How would you diagnose jank and slow startup in a Flutter or React Native app?", "technical", "Hard", ("mobile_developer",), ("Performance",), ("profiling", "render", "startup", "memory")),
    _q("behavioral-intro", "Tell me about yourself and why you are a good fit for this role.", "behavioral", "Easy", tuple(ROLE_PROFILES), ("Behavioral",), ("role", "evidence", "impact", "concise")),
    _q("behavioral-project", "Tell me about a difficult project you worked on. What went wrong and what did you learn?", "behavioral", "Medium", tuple(ROLE_PROFILES), ("Behavioral",), ("situation", "action", "trade-off", "learning")),
    _q("behavioral-conflict", "Describe a disagreement with a teammate and how you handled it.", "behavioral", "Medium", tuple(ROLE_PROFILES), ("Behavioral",), ("context", "communication", "resolution", "reflection")),
    _q("behavioral-failure", "Tell me about a failure or missed deadline. What did you do afterward?", "behavioral", "Medium", tuple(ROLE_PROFILES), ("Behavioral",), ("ownership", "action", "learning", "prevention")),
    _q("behavioral-priority", "How do you prioritize when several important tasks compete for your time?", "behavioral", "Medium", tuple(ROLE_PROFILES), ("Behavioral",), ("impact", "urgency", "trade-offs", "communication")),
    _q("behavioral-unknown", "Tell me about a time you had to learn something quickly to solve a problem.", "behavioral", "Easy", tuple(ROLE_PROFILES), ("Behavioral",), ("learning", "strategy", "evidence", "outcome")),
    _q("behavioral-feedback", "Describe useful feedback you received and how you changed your behavior because of it.", "behavioral", "Medium", tuple(ROLE_PROFILES), ("Behavioral",), ("feedback", "reflection", "change", "result")),
    _q("behavioral-leadership", "Tell me about a time you took ownership without being asked.", "behavioral", "Medium", tuple(ROLE_PROFILES), ("Behavioral",), ("initiative", "ownership", "impact", "communication")),
)

QUESTION_MAP = {item["id"]: item for item in INTERVIEW_QUESTIONS}


def get_role(role_key: str | None) -> RoleProfile:
    if role_key and role_key in ROLE_PROFILES:
        return ROLE_PROFILES[role_key]
    return ROLE_PROFILES["software_engineer"]


def normalized_role_key(role: str | None) -> str:
    candidate = (role or "").strip().lower()
    aliases = {
        "software engineer": "software_engineer",
        "software developer": "software_engineer",
        "backend developer": "backend_developer",
        "frontend developer": "frontend_developer",
        "full stack": "full_stack_developer",
        "full stack developer": "full_stack_developer",
        "data/ml": "data_ml",
        "data/ ml": "data_ml",
        "data ml": "data_ml",
        "ml engineer": "data_ml",
        "devops": "devops_engineer",
        "devops engineer": "devops_engineer",
        "mobile developer": "mobile_developer",
    }
    return aliases.get(candidate, candidate if candidate in ROLE_PROFILES else "")


def role_to_dict(role: RoleProfile) -> dict[str, Any]:
    return {
        "key": role.key,
        "name": role.name,
        "category": role.category,
        "summary": role.summary,
        "requirements": {
            "dsa_topics": list(role.dsa_topics),
            "cs_fundamentals": list(role.cs_fundamentals),
            "role_skills": list(role.role_skills),
            "interview_focus": list(role.interview_focus),
        },
        "company_categories": list(role.company_categories),
        "roadmap": list(role.phases),
    }


def _topic_key(value: str) -> str:
    return " ".join(str(value).strip().lower().replace("&", "and").split())


def topic_match(actual: str, expected: str) -> bool:
    a = _topic_key(actual)
    e = _topic_key(expected)
    return a == e or a.replace("and", "&") == e.replace("and", "&")


def percent(completed: int, total: int) -> int:
    if total <= 0:
        return 0
    return max(0, min(100, round((completed / total) * 100)))


def readiness_band(score: int) -> str:
    if score >= 85:
        return "Interview ready"
    if score >= 70:
        return "Strong progress"
    if score >= 50:
        return "On track"
    if score >= 30:
        return "Building foundations"
    return "Getting started"
