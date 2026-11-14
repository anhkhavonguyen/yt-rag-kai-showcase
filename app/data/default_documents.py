# Copyright 2024
# Directory: yt-rag/app/data/default_documents.py

"""
Default documents for seeding the RAG knowledge base.

They describe Kha Vo, who goes by Kai, and are written from Kai's public
LinkedIn profile: one short topic per document, in the third person, so each one
becomes a single chunk that reads correctly on its own. They hold no analytics,
other people's names, credential IDs or contact details beyond the profile URL.
`/documents` serves them publicly.
"""

from typing import Dict, List

LINKEDIN_URL = "https://www.linkedin.com/in/khavo2907/"

# Default documents for seeding. `title` is shown to visitors when a document is
# cited as a source; it isn't stored with the chunks.
DEFAULT_DOCUMENTS: List[Dict[str, str]] = [
    {
        'chunk_id': 'kai_overview_v1',
        'title': 'Who Kai is',
        'source': LINKEDIN_URL,
        'text': '''Who is Kai? Kha Vo, who goes by Kai, is a Team Lead and software engineer based in Ho Chi Minh City, Vietnam. Kai's LinkedIn headline is "Team Lead | Enterprise Software & AI Solutions | Forward Deployed Engineering | .NET & Azure". Kai has designed, developed and delivered enterprise software since 2014, more than 12 years as of 2026, combining hands-on engineering, technical leadership, system architecture, cloud engineering and production operations. Kai specializes in turning complex business requirements into scalable, reliable and maintainable software.

At Orient Software Development Corp., Kai leads technical development for DEKRA's Global Vehicle Inspection Booking platform, working with international stakeholders and teams across multiple markets. Before that, Kai was a software engineer at DXC Technology Vietnam.

Kai has worked in automotive inspection and booking, healthcare management, retail inventory, payment solutions, cloud computing and Microsoft 365 integrations, and is now expanding into generative AI and AI-powered enterprise applications.

Kai's philosophy: understand the problem, engineer the solution, and own the outcome.'''
    },
    {
        'chunk_id': 'kai_current_role_v1',
        'title': 'Current role: DEKRA booking platform',
        'source': LINKEDIN_URL,
        'text': '''Kai (Kha Vo) has worked full-time at Orient Software Development Corp. in Ho Chi Minh City since July 2016, in a hybrid setup. Kai is Team Lead for DEKRA's Global Vehicle Inspection Booking platform, a multi-tenant enterprise solution serving multiple international markets, and has worked onsite at DEKRA's headquarters in Germany.

In technical leadership and delivery, Kai leads development activities with developers, product owners and international stakeholders, translates business requirements into technical designs and scalable solutions, and drives technical discussions, code reviews, problem-solving and continuous improvement.

In enterprise software and architecture, Kai designs and develops backend services and REST APIs with C#, .NET, ASP.NET Core and SQL Server, and builds frontend applications with Angular and TypeScript. The work covers multi-tenant architecture, country-specific workflows, and third-party integrations including payment, SMS and CAPTCHA services.'''
    },
    {
        'chunk_id': 'kai_cloud_production_v1',
        'title': 'Azure and production work',
        'source': LINKEDIN_URL,
        'text': '''On DEKRA's Global Vehicle Inspection Booking platform, Kai (Kha Vo) designs and maintains Microsoft Azure solutions using App Services, API Management, Azure Cache for Redis, Managed Identity and Private Endpoints. Kai improves scalability, performance, caching and distributed concurrency handling, and drives improvements in security, monitoring and cloud infrastructure.

Kai troubleshoots complex production issues involving high traffic, duplicate bookings and system reliability, supports releases, production deployments and incident resolution, and works with infrastructure teams to keep the platform stable.

In 2026 Kai was part of the team that got the platform running again over a weekend of unexpected production issues, working across three continents and time zones, and was thanked publicly by a DEKRA colleague. Kai's lesson from it: communication matters as much as technical skills, and sometimes the fastest path forward is picking up the phone and solving problems together.'''
    },
    {
        'chunk_id': 'kai_earlier_projects_v1',
        'title': 'Other enterprise projects',
        'source': LINKEDIN_URL,
        'text': '''Besides the DEKRA platform, Kai (Kha Vo) has worked on other enterprise projects at Orient Software Development Corp.: CloudInc (cloud computing), ASPIT (healthcare management), TOG (retail inventory), ESPOS (payment solutions) and Rencore (Microsoft 365 and Azure). Across these projects Kai gained experience in healthcare, retail, payments, cloud computing and Microsoft 365 integrations, in addition to automotive inspection and booking.'''
    },
    {
        'chunk_id': 'kai_dxc_v1',
        'title': 'DXC Technology Vietnam (2014–2016)',
        'source': LINKEDIN_URL,
        'text': '''From September 2014 to June 2016, Kai (Kha Vo) was a Software Engineer at DXC Technology Vietnam in Ho Chi Minh City. Kai was part of a 30-member development team on the Jurong Town Corporation (JTC) JIM project in Singapore, taking part in business requirement analysis and software development, implementing enterprise application features with the team, and contributing to problem-solving and project delivery. The role gave Kai experience in a large enterprise development team with structured software delivery processes.'''
    },
    {
        'chunk_id': 'kai_expertise_v1',
        'title': 'Core expertise',
        'source': LINKEDIN_URL,
        'text': '''What can Kai do? Kha Vo (Kai) has core expertise in five areas.

Enterprise software engineering: C#, .NET, ASP.NET Core, Angular, REST APIs, SQL Server and distributed applications.

Cloud and distributed systems: Microsoft Azure, App Services, API Management, Azure Cache for Redis, cloud architecture, scalability and system reliability.

Solution architecture: multi-tenant platforms, system integration, database design, distributed locking, caching strategies and performance optimization.

Technical leadership: leading development activities, technical problem-solving, architecture discussions, mentoring, and collaboration with international stakeholders.

Production engineering: troubleshooting complex production incidents and improving application performance, security, availability and operational reliability.

Kai is also expanding into generative AI: large language models, retrieval-augmented generation (RAG), AI agents and AI-assisted software engineering.'''
    },
    {
        'chunk_id': 'kai_ai_focus_v1',
        'title': 'AI focus',
        'source': LINKEDIN_URL,
        'text': '''Kai (Kha Vo) is actively expanding expertise in generative AI and AI-powered enterprise applications, with a focus on large language models (LLMs) and retrieval-augmented generation (RAG); AI agents and tool or function calling; AI-assisted software engineering and agentic development workflows; and applying AI to real-world enterprise business processes.

Kai earned Anthropic's Claude Code in Action certification in March 2026, and lists GitHub Copilot and Replit Agent among the tools Kai uses. Kai follows the shift from the traditional software development lifecycle to an agentic one, in which AI agents write much of the code and people review and govern their work.'''
    },
    {
        'chunk_id': 'kai_education_certifications_v1',
        'title': 'Education and certifications',
        'source': LINKEDIN_URL,
        'text': '''Kai (Kha Vo) holds an Engineer's Degree in Information Technology from Sai Gon University (2010 to 2014).

Kai lists 13 licenses and certifications on LinkedIn, including Claude Code in Action from Anthropic (March 2026), AWS Educate Machine Learning Foundations from Amazon Web Services (July 2025), Oracle Cloud Infrastructure 2025 Certified AI Foundations Associate from Oracle (2025), and Microsoft Certified Professional with the Programming in C# exam.

Kai also completed the code labs at Build with AI Ho Chi Minh City 2026 and received a certificate of completion.'''
    },
    {
        'chunk_id': 'kai_career_direction_v1',
        'title': 'Career direction',
        'source': LINKEDIN_URL,
        'text': f'''Kai (Kha Vo) is particularly interested in Forward Deployed Engineering opportunities at the intersection of AI, enterprise software and cloud engineering.

Kai enjoys working closely with customers and business stakeholders to understand their challenges, design practical solutions, build working prototypes, and deliver technology that creates measurable business value.

Kai's philosophy: understand the problem, engineer the solution, and own the outcome.

For opportunities, or anything this profile doesn't cover, contact Kai on LinkedIn: {LINKEDIN_URL}'''
    },
    {
        'chunk_id': 'kai_community_writing_v1',
        'title': 'Writing and community',
        'source': LINKEDIN_URL,
        'text': '''Kai (Kha Vo) writes technical articles on Medium, including "Synchronous/Asynchronous programming … think more about the definition", which explores synchronous and asynchronous programming, threading and tasks, and "On the road to understand Microservices and demonstrate the concept with Clean Architecture", Kai's first article.

Kai takes part in developer community events. In 2026 Kai joined Build with AI Ho Chi Minh City, organized by GDG Ho Chi Minh City with Google for Developers, with sessions on where Google AI is heading, vibe coding, deploying and observing AI agents on Google Cloud Run, and using the Gemini API to extract data from invoices and forms. Kai also joined DEV@Cafe – GitHub Copilot Dev Days 2026 at NashTech, including a multi-agent lab on AI agents collaborating on development tasks.

Kai sees continuous learning as essential in tech.'''
    },
]

# Title of each default document, by document ID (the chunk ID before "#").
DOCUMENT_TITLES: Dict[str, str] = {doc['chunk_id']: doc['title'] for doc in DEFAULT_DOCUMENTS}
