from types import SimpleNamespace

from app.routers import interviews as i


def batch(module="project", title="Agent Platform", description="Built RAG with FastAPI and Redis", limit=5):
    return i.QuestionBatch(
        module=module,
        point_id=f"{module}:1",
        title=title,
        source_section=title,
        description=description,
        context=f"{title}\n{description}",
        limit=limit,
    )


def test_template_batch_and_company_bias_contracts():
    b = batch()
    assert i._fallback_point({"name": "Agent", "description": "RAG service"})["title"] == "Agent"
    assert i._dedupe_text([" A ", "a", "B", ""]) == ["A", "B"]
    interview = SimpleNamespace(template_config_snapshot={"template_id": "technical_first"}, interview_template_id=None)
    assert i._interview_template_config(interview)["template_id"] == "technical_first"
    assert i._interview_template_config(None)["template_id"]
    template = {
        "template_id": "technical_first",
        "name": "Technical",
        "description": "deep dive",
        "question_focus": ["architecture", "tradeoffs"],
        "report_focus": ["evidence"],
        "module_ratios": {"project": 1},
        "module_question_limits": {"project": 3, "system_design": 1, "agent_fundamentals": 1},
        "scoring_dimensions": [
            {"key": "technical_depth", "source_score_keys": ["technical_depth"]},
            {"key": "communication", "source_score_keys": ["communication"]},
        ],
        "module_order": ["project", "system_design", "agent_fundamentals"],
    }
    assert "architecture" in i._template_prompt_context(template)
    assert "evidence" in i._template_score_context(template)
    assert i._clone_batch_with_limit(b, 2).limit == 2
    applied = i._apply_template_to_batches([b, batch("behavioral")], template)
    assert [x.module for x in applied] == ["project"] and applied[0].limit == 3
    assert i._apply_template_to_batches([b], None)[0] is b
    scores = i._template_dimension_scores(template, {"technical_depth": 80, "communication": "70", "bad": None})
    assert scores == {"technical_depth": 80.0, "communication": 70.0}

    snapshot = {
        "profile_id": "p1",
        "matched_company": "Acme",
        "matched_position": "backend",
        "profile_confidence": "high",
        "source_count": 8,
        "matched_rounds": [{"round_type": "technical_first", "name": "first"}],
        "matched_topics": [{"name": "database"}],
        "frequent_questions": [
            {
                "canonical_question": "How Redis works?",
                "round_type": "technical_first",
                "difficulty": "medium",
                "source_count": 3,
            }
        ],
        "referenced_questions": ["How Redis works?"],
        "generated_at": "2026-08-27T00:00:00Z",
    }
    trace = i._company_generation_trace(snapshot)
    assert trace["matched_company"] == "Acme"
    biased, company_trace = i._template_with_company_profile_bias(template, snapshot)
    assert company_trace["target_module"] == "agent_fundamentals" and biased["module_question_limits"]["agent_fundamentals"] == 2
    unchanged, empty_trace = i._template_with_company_profile_bias(template, None)
    assert unchanged == template and empty_trace == {}
    assert i._safe_target_text("  value  ", 3) == "val"
    assert i._safe_target_text("", 3) is None


def test_evidence_question_quality_and_report_helpers():
    b = batch()
    snippets = [
        SimpleNamespace(
            section="project",
            item_title="Agent",
            content="Implemented FastAPI RAG retrieval with Qdrant and measured latency",
            score=2.5,
            retrieval_source="hybrid",
            to_dict=lambda: {
                "section_label": "Project",
                "section": "project",
                "item_title": "Agent",
                "content": "Implemented FastAPI RAG retrieval with Qdrant and measured latency",
                "score": 2.5,
                "retrieval_source": "hybrid",
            },
        )
    ]
    evidence = i._resume_evidence_dicts(snippets, b)
    assert evidence[0]["source_section"] == "Project" and evidence[0]["retrieval_score"] == 2.5
    context = i._evidence_context(evidence)
    assert "Qdrant" in context
    specific = "In the Agent project, why did you choose Qdrant for RAG retrieval?"
    assert i._question_specificity_score(specific, evidence) >= 2
    quality = i._question_quality(specific, b, evidence)
    assert quality["specificity_score"] >= 2
    assert i._text_excerpt("  a\n b  ", 10) == "a b"

    q = SimpleNamespace(
        question_text="Explain RAG tradeoffs",
        question_type="technical",
        module="project",
        source_section="Agent",
        score_dimensions={"technical_depth": 80, "communication": 70},
        evidence=[{"source_snippet": "architecture evidence"}],
        score=75,
        total_score=75,
        answer="Detailed answer",
        user_answer="Detailed answer",
        score_details={"technical_accuracy": {"risk": "high", "issue": "add metrics"}},
        question="Explain RAG tradeoffs",
        point_title="Agent",
        feedback={
            "strengths": ["clear"],
            "improvements": ["metrics"],
            "reference_answer": "reference",
            "score_details": {},
        },
    )
    response = {
        "score_details": {
            "technical_depth": {"score": 82, "evidence": "architecture", "reason": "good", "suggestion": "add metrics"}
        }
    }
    detail = i._score_detail("technical_depth", 82, q.answer, q, response)
    assert detail["score"] == 82
    normalized = i._normalize_score_details(response, {"technical_depth": 82, "communication": 70}, q.answer, q)
    assert normalized["technical_depth"]["score"] == 82
    assert i._hire_signal(90) == "strong"
    assert i._hire_signal(76) == "positive"
    assert i._hire_signal(61) == "borderline"
    assert i._hire_signal(40) == "weak"

    interview = SimpleNamespace(
        template_config_snapshot={"template_id": "technical_first", "name": "Technical"},
        interview_template_id=None,
        company_profile_snapshot={},
        title="mock",
        dimension_scores={"technical_accuracy": 8},
        target_company=None,
        target_position=None,
        total_score=75,
        weak_points=["metrics"],
    )
    report = i._build_report_details(interview, [q])
    assert report["module_scores"]["project"] == 75 and report["hire_signal"]
    template_report = i._template_report_details(interview, [q])
    assert template_report["interview_template"]["template_id"] == "technical_first"


def test_question_safety_normalization_and_merging():
    b = batch()
    assert i._clean_question_text("How does Redis work?") == "How does Redis work?"
    assert i._normalize_question_for_similarity("Redis，Consistency？！")
    assert i._question_intent("Why did you choose Redis?")
    assert i._question_similarity_key("Why did you choose Redis?")
    assert i._contains_system_meta_question(i.SYSTEM_META_QUESTION_MARKERS[0])
    assert not i._question_has_valid_anchor("What are your strengths?", b)
    assert i._question_has_valid_anchor("In Agent Platform, how did FastAPI handle retries?", b)
    assert i._is_bad_question(i.SYSTEM_META_QUESTION_MARKERS[0], b)
    assert i._is_bad_question("short", b)
    assert not i._is_bad_question("In Agent Platform, how did you design Redis retries and why?", b)
    seen = ["In Agent Platform, how did you design Redis retries and why?"]
    keys = {i._question_similarity_key(seen[0])}
    assert i._is_duplicate_question(seen[0], seen, keys)
    assert not i._is_duplicate_question("How did PostgreSQL indexes improve latency?", seen, keys)
    assert i._safe_score("88") == 10.0 and i._safe_score("bad") is None
    assert i._normalize_score_dimensions({"technical_accuracy": "8.8", "bad": "x"}) == {"technical_accuracy": 8.8}
    assert i._normalize_score_dimensions([]) == {}

    response_items = i._response_question_items(
        {
            "questions": [
                {"question": "In Agent Platform, how did you design Redis retries and why?", "type": "technical"},
                "bad",
            ]
        }
    )
    assert len(response_items) == 1
    fallback = i._module_fallback_questions(b)
    merged = i._merge_question_items(response_items, fallback, 3, batch=b)
    assert len(merged) == 3 and all(item["question_text"] for item in merged)
    assert (
        i._infer_question_type("Please design a scalable API architecture", batch("system_design")) == "system_design"
    )
    assert i._infer_question_type("Tell me about a conflict", batch("behavioral")) == "behavioral_star"


def test_resume_record_and_bank_helpers():
    assert i._compact_text({"a": 1})
    assert i._normalize_records({"name": "A"}) == [{"name": "A"}]
    assert i._normalize_records([{"name": "A"}, "text"])[1]["description"] == "text"
    assert i._clean_label("  Agent  ", "fallback") == "Agent"
    project = {"name": "Agent", "description": "Built RAG retrieval", "technologies": ["FastAPI", "Qdrant"]}
    assert i._record_title(project, "fallback", is_project=True) == "Agent"
    assert "RAG" in i._record_description(project)
    assert i._looks_placeholder("???")
    assert not i._is_weak_record(project, is_project=True)
    assert i._is_weak_record({"name": "???"}, is_project=True)

    raw = "Summary\ntext\n\nProjects\nAgent Platform\nBuilt FastAPI RAG with Qdrant and Redis.\nImproved retrieval latency by 30%.\n\nExperience\nAcme Backend Intern\nBuilt APIs and tests."
    lines = i._resume_section_lines(raw, ("Projects",))
    assert lines and "Agent" in lines[0]
    assert i._looks_record_heading("Agent Platform 项目")
    records = i._records_from_raw_section(raw, ("Projects",), fallback_prefix="Project", is_project=True)
    assert records
    assert i._records_with_raw_fallback([{"name": "project 1"}], records, is_project=True) == records
    assert i._records_with_raw_fallback([project], records, is_project=True)

    terms = i._detect_tech_terms("Python FastAPI Redis RAG Qdrant BGE-M3 RRF")
    assert {"FastAPI", "Redis", "RAG", "Qdrant"}.issubset(terms)
    skills = i._extract_resume_skills({"skills": ["Python", "FastAPI"]}, raw, "Redis backend")
    assert "Python" in skills and "Redis" in skills
    assert "Redis" in i._term_question("Redis", "Agent Platform", "project")
    assert i._extract_bank_question("Question: How does Redis work?\nAnswer: x") == ""
    assert "project_deep_dive" in i._compatible_bank_sections("project")
    contextual = i._contextualize_bank_question("How does Redis work?", batch())
    assert "Agent Platform" in contextual
