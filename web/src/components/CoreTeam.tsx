interface TeamMember {
  name: string;
  handle: string;
  avatarUrl: string;
  githubUrl: string;
  linkedinUrl: string;
}

const TEAM: TeamMember[] = [
  {
    name: "Yoav Lax",
    handle: "YoavLax",
    avatarUrl: "https://github.com/YoavLax.png",
    githubUrl: "https://github.com/YoavLax",
    linkedinUrl: "https://www.linkedin.com/in/yoav-lax-2127b9189/",
  },
  {
    name: "Bechor Simhaev",
    handle: "bechor25",
    avatarUrl: "https://github.com/bechor25.png",
    githubUrl: "https://github.com/bechor25",
    linkedinUrl: "https://www.linkedin.com/in/bechor-simhaev/",
  },
];

const linkClass =
  "focus-ring rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-600 transition-colors hover:border-primary-300 hover:text-primary-700 dark:border-night-border dark:bg-night-card dark:text-night-muted dark:hover:border-primary-600 dark:hover:text-primary-400";

export function CoreTeam() {
  return (
    <section className="flex flex-col items-center gap-3">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-night-muted">
        Built by
      </h2>
      <div className="flex flex-wrap items-center justify-center gap-3">
        {TEAM.map((member) => (
          <div
            key={member.handle}
            className="flex items-center gap-3 rounded-xl border border-gray-200 bg-white/70 px-4 py-3 shadow-card dark:border-night-border dark:bg-night-card/70"
          >
            <img
              src={member.avatarUrl}
              alt={member.name}
              width={40}
              height={40}
              loading="lazy"
              className="h-10 w-10 rounded-full border border-gray-200 dark:border-night-border"
            />
            <div className="flex flex-col items-start gap-1.5">
              <span className="text-sm font-medium leading-none text-gray-900 dark:text-night-text">
                {member.name}
              </span>
              <div className="flex items-center gap-1.5">
                <a
                  href={member.githubUrl}
                  target="_blank"
                  rel="noreferrer noopener"
                  className={linkClass}
                >
                  GitHub
                </a>
                <a
                  href={member.linkedinUrl}
                  target="_blank"
                  rel="noreferrer noopener"
                  className={linkClass}
                >
                  LinkedIn
                </a>
              </div>
            </div>
          </div>
        ))}
      </div>
      <a
        href="https://github.com/YoavLax/agent-compass"
        target="_blank"
        rel="noreferrer noopener"
        className="focus-ring inline-flex items-center gap-1.5 rounded-md text-xs font-medium text-gray-500 transition-colors hover:text-primary-700 hover:underline dark:text-night-muted dark:hover:text-primary-400"
      >
        <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true">
          <path d="M12 .5A11.5 11.5 0 0 0 .5 12c0 5.1 3.29 9.42 7.86 10.95.58.1.79-.25.79-.56v-2.1c-3.2.7-3.87-1.36-3.87-1.36-.53-1.33-1.29-1.69-1.29-1.69-1.05-.72.08-.7.08-.7 1.17.08 1.78 1.2 1.78 1.2 1.03 1.77 2.71 1.26 3.37.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.68 0-1.26.45-2.28 1.19-3.09-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.18 1.18a11 11 0 0 1 5.8 0c2.2-1.49 3.17-1.18 3.17-1.18.64 1.59.24 2.76.12 3.05.74.81 1.18 1.83 1.18 3.09 0 4.41-2.69 5.39-5.25 5.67.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 23.5 12 11.5 11.5 0 0 0 12 .5Z" />
        </svg>
        Go to Agent Compass repository on GitHub &rarr;
      </a>
      <p className="flex items-center gap-1.5 text-xs text-gray-400 dark:text-night-muted">
        Enjoying AgentCompass? Give us a star
        <svg viewBox="0 0 16 16" width="13" height="13" fill="currentColor" className="text-warning-500" aria-hidden="true">
          <path d="M8 .25a.75.75 0 0 1 .673.418l1.882 3.815 4.21.612a.75.75 0 0 1 .416 1.279l-3.046 2.97.719 4.192a.751.751 0 0 1-1.088.791L8 12.347l-3.766 1.98a.75.75 0 0 1-1.088-.79l.72-4.194L.818 6.374a.75.75 0 0 1 .416-1.28l4.21-.611L7.327.668A.75.75 0 0 1 8 .25Z" />
        </svg>
      </p>
    </section>
  );
}

export default CoreTeam;
