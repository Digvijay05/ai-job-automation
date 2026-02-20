"""Generate mock test resumes for the recruitment workflow.

Requirements:
- reportlab

Outputs realistic PDF resumes targeting different roles (Backend, Data, Quant, SecOps, ML).
Uses reportlab platypus for clean, ATS-friendly structured PDFs.

Since WeasyPrint requires GTK3 system libraries (which fail on vanilla Windows),
we use reportlab to ensure deterministic, zero-dependency generation across all OSes.
"""
from __future__ import annotations

import logging
from pathlib import Path

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem
except ImportError:
    import sys
    print("Error: reportlab is required.")
    print("Run: pip install reportlab")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("generate_resumes")

# ──────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "resumes"

# Ensure output dir exists
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Shared required email for all test scenarios
CONTACT_EMAIL = "digvijayjadav.dev@gmail.com"

# ──────────────────────────────────────────────────
# Candidate Mock Data
# ──────────────────────────────────────────────────
CANDIDATES = [
    {
        "filename": "Alex_Chen_Backend.pdf",
        "name": "Alex Chen",
        "email": CONTACT_EMAIL,
        "phone": "+1 (555) 019-2834",
        "location": "San Francisco, CA",
        "linkedin": "linkedin.com/in/alexchen-backend",
        "summary": "Senior Backend Engineer with 6 years of experience scaling distributed systems and microservices. Passionate about Kubernetes, Go, and building low-latency APIs for AI workloads.",
        "skills": ["Python", "Go", "Kubernetes", "Docker", "PostgreSQL", "Redis", "FastAPI", "gRPC", "AWS"],
        "experience": [
            {
                "title": "Backend Engineer",
                "company": "DataTech Solutions",
                "location": "San Francisco, CA",
                "dates": "Mar 2021 - Present",
                "bullets": [
                    "Architected and deployed a distributed caching layer using Redis, reducing API p99 latency by 45%.",
                    "Migrated legacy monolithic application to 15+ Go microservices deployed on Kubernetes.",
                    "Implemented robust CI/CD pipelines using GitHub Actions, reducing deployment time from hours to 15 minutes."
                ]
            },
            {
                "title": "Software Engineer",
                "company": "CloudScape Systems",
                "location": "Seattle, WA",
                "dates": "Jun 2018 - Feb 2021",
                "bullets": [
                    "Developed high-throughput data ingestion APIs in Python mapping 5TB of log data daily.",
                    "Reduced cloud infrastructure costs by 20% by refactoring inefficient database queries.",
                    "Mentored 2 junior engineers."
                ]
            }
        ],
        "projects": [
            {
                "name": "Distributed Task Queue",
                "description": "Open-source asynchronous task queue mimicking Celery but optimized for massive fan-out.",
                "tech": "Go, Redis, gRPC"
            }
        ],
        "education": [
            {
                "degree": "B.S. Computer Science",
                "university": "University of Washington",
                "grad_year": "2018"
            }
        ]
    },
    {
        "filename": "Jordan_Smith_Data.pdf",
        "name": "Jordan Smith",
        "email": CONTACT_EMAIL,
        "phone": "+1 (555) 832-1102",
        "location": "Austin, TX (Remote)",
        "linkedin": "linkedin.com/in/jordansmith-data",
        "summary": "Data Platform Engineer specializing in building robust ETL/ELT pipelines and scalable data warehouses. Experienced in managing petabyte-scale data ingestion for analytics and ML models.",
        "skills": ["Python", "Apache Spark", "Airflow", "Snowflake", "dbt", "SQL", "Kafka"],
        "experience": [
            {
                "title": "Data Engineer",
                "company": "RetailAnalytics",
                "location": "Austin, TX",
                "dates": "Aug 2020 - Present",
                "bullets": [
                    "Designed and maintained Airflow DAGs to orchestrate 200+ daily data pipelines.",
                    "Led the migration from legacy Redshift warehouse to Snowflake, improving query performance by 3x.",
                    "Built streaming pipelines in Kafka to process 50,000 events/second."
                ]
            }
        ],
        "projects": [
            {
                "name": "dbt-macro-library",
                "description": "A collection of dbt macros for advanced financial modeling and time-series aggregation.",
                "tech": "SQL, Jinja, dbt"
            }
        ],
        "education": [
            {
                "degree": "M.S. Data Science",
                "university": "University of Texas at Austin",
                "grad_year": "2020"
            },
            {
                "degree": "B.S. Mathematics",
                "university": "Texas A&M University",
                "grad_year": "2018"
            }
        ]
    },
    {
        "filename": "Maria_Garcia_Quant.pdf",
        "name": "Maria Garcia",
        "email": CONTACT_EMAIL,
        "phone": "+1 (555) 443-9821",
        "location": "New York, NY",
        "linkedin": "linkedin.com/in/mariagarcia-quant",
        "summary": "Quantitative Developer focused on ultra-low latency execution systems and C++ kernel optimization. Strong background in mathematics and network programming for algorithmic trading.",
        "skills": ["C++20", "Python", "Linux Kernel Optimization", "TCP/IP Networking", "Boost", "CUDA"],
        "experience": [
            {
                "title": "Quantitative Developer",
                "company": "AlphaStream Capital",
                "location": "New York, NY",
                "dates": "Jan 2019 - Present",
                "bullets": [
                    "Optimized C++ order execution engine, shaving 2.5 microseconds off critical path latency.",
                    "Implemented custom network stack bypassing Linux kernel for direct nic communications (kernel bypass).",
                    "Collaborated with researchers to deploy multi-asset statistical arbitrage strategies."
                ]
            },
            {
                "title": "C++ Software Engineer",
                "company": "HighFrequency Tech",
                "location": "Chicago, IL",
                "dates": "Jul 2016 - Dec 2018",
                "bullets": [
                    "Maintained market data feed handlers for NASDAQ and CME.",
                    "Reduced memory allocation bottlenecks in the matching engine."
                ]
            }
        ],
        "projects": [
            {
                "name": "FastPCap",
                "description": "Zero-copy packet capture library written in C++ for analyzing market data microbursts.",
                "tech": "C++, DPDK"
            }
        ],
        "education": [
            {
                "degree": "M.S. Financial Engineering",
                "university": "Columbia University",
                "grad_year": "2016"
            },
            {
                "degree": "B.A. Physics",
                "university": "University of Chicago",
                "grad_year": "2014"
            }
        ]
    },
    {
        "filename": "David_Kim_SecOps.pdf",
        "name": "David Kim",
        "email": CONTACT_EMAIL,
        "phone": "+1 (555) 776-3390",
        "location": "New York, NY",
        "linkedin": "linkedin.com/in/davidkim-secops",
        "summary": "Security Operations Engineer protecting enterprise infrastructure against advanced threats. Expert in SIEM tuning, vulnerability management, and incident response automation.",
        "skills": ["Splunk", "AWS Security", "Python", "CrowdStrike", "Bash", "Incident Response", "Penetration Testing"],
        "experience": [
            {
                "title": "Security Analyst",
                "company": "FinSecure Bank",
                "location": "New York, NY",
                "dates": "Oct 2021 - Present",
                "bullets": [
                    "Automated level 1 SOC triage using Python scripts, reducing MTTD by 40%.",
                    "Managed Splunk SIEM deployment, optimizing rule sets to reduce false positives by 60%.",
                    "Led incident response for 3 major security events involving compromised credentials."
                ]
            },
            {
                "title": "IT Systems Admin",
                "company": "TechRetail",
                "location": "New York, NY",
                "dates": "Mar 2019 - Sep 2021",
                "bullets": [
                    "Managed Active Directory, Office365, and IAM policies for 500+ employees.",
                    "Implemented zero-trust architecture roll-out."
                ]
            }
        ],
        "projects": [
            {
                "name": "AutoTriage",
                "description": "Python CLI tool to enrich IP and Domain indicators from VirusTotal and AbuseIPDB automatically.",
                "tech": "Python, REST APIs"
            }
        ],
        "education": [
            {
                "degree": "B.S. Cybersecurity",
                "university": "Rochester Institute of Technology",
                "grad_year": "2019"
            }
        ]
    },
    {
        "filename": "Aisha_Patel_ML.pdf",
        "name": "Aisha Patel",
        "email": CONTACT_EMAIL,
        "phone": "+1 (555) 234-5678",
        "location": "Boston, MA",
        "linkedin": "linkedin.com/in/aishapatel-ml",
        "summary": "Machine Learning Engineer specializing in Computer Vision and deep learning optimization. Proven track record deploying complex neural networks into medical and autonomous production environments.",
        "skills": ["Python", "PyTorch", "TensorFlow", "OpenCV", "CUDA", "TensorRT", "C++"],
        "experience": [
            {
                "title": "ML Engineer",
                "company": "VisionMed Diagnostics",
                "location": "Boston, MA",
                "dates": "May 2020 - Present",
                "bullets": [
                    "Trained and deployed segmentation models (U-Net) for MRI analysis, achieving 98% accuracy.",
                    "Optimized model inference speed by 4x using NVIDIA TensorRT and CUDA optimizations.",
                    "Built reproducible training pipelines using PyTorch Lightning and Weights & Biases."
                ]
            },
            {
                "title": "Computer Vision Intern",
                "company": "DriveAI",
                "location": "San Jose, CA",
                "dates": "Jun 2019 - Aug 2019",
                "bullets": [
                    "Improved bounding box regression for pedestrian detection by 5% using custom anchor box generation."
                ]
            }
        ],
        "projects": [
            {
                "name": "MedNet OpenSource",
                "description": "Open-source repository of pre-trained models for classifying common thorax diseases from X-rays.",
                "tech": "PyTorch, Flask, Docker"
            }
        ],
        "education": [
            {
                "degree": "M.S. Computer Science (AI Track)",
                "university": "Massachusetts Institute of Technology",
                "grad_year": "2020"
            }
        ]
    }
]

# ──────────────────────────────────────────────────
# Main Generator (ReportLab)
# ──────────────────────────────────────────────────
def generate_pdfs() -> None:
    logger.info("Initializing resume generator (ReportLab)...")
    
    # Define styles
    styles = getSampleStyleSheet()
    
    style_name = ParagraphStyle(
        'Name',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#111111'),
        spaceAfter=6,
        fontName='Helvetica-Bold'
    )
    
    style_contact = ParagraphStyle(
        'Contact',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#555555'),
        spaceAfter=15,
        fontName='Helvetica'
    )
    
    style_heading = ParagraphStyle(
        'Heading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#222222'),
        spaceAfter=8,
        spaceBefore=15,
        fontName='Helvetica-Bold',
        borderWidth=1,
        borderColor=colors.lightgrey,
        borderPadding=3
    )
    
    style_job_title = ParagraphStyle(
        'JobTitle',
        parent=styles['Heading3'],
        fontSize=12,
        textColor=colors.HexColor('#111111'),
        spaceAfter=3,
        fontName='Helvetica-Bold'
    )
    
    style_meta = ParagraphStyle(
        'Meta',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#666666'),
        spaceAfter=6,
        fontName='Helvetica-Oblique'
    )
    
    style_normal = ParagraphStyle(
        'Body',
        parent=styles['Normal'],
        fontSize=11,
        leading=14,
        spaceAfter=8,
        fontName='Helvetica'
    )

    success_count = 0
    for profile in CANDIDATES:
        try:
            filename = profile.pop("filename")
            out_file = OUT_DIR / filename
            
            doc = SimpleDocTemplate(
                str(out_file),
                pagesize=letter,
                rightMargin=50,
                leftMargin=50,
                topMargin=50,
                bottomMargin=50
            )
            
            story = []
            
            # Header
            story.append(Paragraph(profile['name'], style_name))
            contact_str = f"{profile['email']} | {profile['phone']} | {profile['location']} | {profile['linkedin']}"
            story.append(Paragraph(contact_str, style_contact))
            
            # Summary
            story.append(Paragraph(profile['summary'], style_normal))
            
            # Skills
            story.append(Paragraph("SKILLS", style_heading))
            story.append(Paragraph(f"<b>Core Competencies:</b> {', '.join(profile['skills'])}", style_normal))
            
            # Experience
            story.append(Paragraph("EXPERIENCE", style_heading))
            for exp in profile['experience']:
                # Title and Company
                story.append(Paragraph(f"{exp['title']} at {exp['company']}", style_job_title))
                
                # Dates and Location
                meta_str = f"{exp['location']}   •   {exp['dates']}"
                story.append(Paragraph(meta_str, style_meta))
                
                # Bullets
                bullets = []
                for bullet in exp['bullets']:
                    bullets.append(ListItem(Paragraph(bullet, style_normal)))
                story.append(ListFlowable(bullets, bulletType='bullet', start='bulletchar'))
                story.append(Spacer(1, 10))
                
            # Projects
            story.append(Paragraph("PROJECTS", style_heading))
            for proj in profile['projects']:
                story.append(Paragraph(proj['name'], style_job_title))
                story.append(Paragraph(proj['description'], style_normal))
                story.append(Paragraph(f"<b>Tech:</b> {proj['tech']}", style_normal))
                story.append(Spacer(1, 5))
                
            # Education
            story.append(Paragraph("EDUCATION", style_heading))
            for edu in profile['education']:
                story.append(Paragraph(edu['degree'], style_job_title))
                meta_str = f"{edu['university']}   •   {edu['grad_year']}"
                story.append(Paragraph(meta_str, style_meta))
                story.append(Spacer(1, 5))
                
            # Generate PDF
            logger.info("Generating: %s", out_file.name)
            doc.build(story)
            success_count += 1
            
        except Exception as exc:
            logger.exception("Failed to generate resume for %s", profile.get("name", "Unknown"))

    logger.info("Successfully generated %d/%d test resumes to %s", success_count, len(CANDIDATES), OUT_DIR)

if __name__ == "__main__":
    generate_pdfs()
