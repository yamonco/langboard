# Langboard 🚀

**AI-Powered Project Management & Collaboration Tool**

Langboard is an AI-driven project management solution developed by YAMON. Designed to empower teams with intelligent automation and seamless collaboration, Langboard is open-source and free for individual and non-profit users. For commercial usage, companies must sponsor via [GitHub Sponsors](https://github.com/sponsors/yamonco) or secure a separate licensing agreement.

---

## 🌟 Key Features

-   **🤖 AI Task Agent**

    -   **Intelligent Automation:** Analyze tasks and project data with advanced AI to provide smart recommendations and automate routine workflows.
    -   **Predictive Insights:** Leverage predictive analytics to foresee bottlenecks and optimize task assignments.

-   **🔗 Edge-Based Card Linking**

    -   **Visual Task Mapping:** Connect tasks with dynamic, interactive cards to clearly visualize dependencies and workflows.
    -   **Customizable Links:** Easily adjust and customize relationships between tasks for better project planning.

-   **🔍 RAG Search Functionality**

    -   **Instant Access:** Utilize vector-based search technology to retrieve project information in seconds.
    -   **Context-Aware Results:** Get smart, contextually relevant search outcomes to enhance your project understanding.
        onboarding.

-   **📊 Real-Time Analytics & Reporting**

    -   **Dynamic Dashboards:** Monitor project progress and team performance with interactive charts and real-time metrics.
    -   **Data-Driven Decisions:** Empower your team with actionable insights to drive productivity and success.

-   **💬 Collaboration & Notifications**
    -   **Seamless Communication:** Integrate chat and notification systems to keep every team member in the loop.
    -   **Activity Feeds:** Stay updated on project changes, task completions, and team interactions instantly.

---

## 🐳 Docker Installation and Setup

Langboard is optimized for Docker deployment. The repository includes a Dockerfile and docker-compose configuration for a streamlined setup.

### Prerequisites

-   [Docker](https://docs.docker.com/get-docker/) (version 20.10 or higher)
-   [Docker Compose](https://docs.docker.com/compose/install/) (if not bundled with your Docker installation)

### Steps to Build and Run

1. **Clone the Repository**

    ```bash
    git clone https://github.com/yamonco/langboard.git
    cd langboard
    ```

2. **Configure Environment Variables**

    - Duplicate the `.env.example` file and rename it to `.env`.
    - Update the file with necessary environment variables such as API keys, database connections, and port configurations.

3. **Build and Run Docker Container**

    ```bash
    make start_docker_prod
    ```

4. **Access the Application**

    - Once running, access Langboard at `http://localhost:NGINX_FRONTEND_EXPOSE_PORT` (replace `NGINX_FRONTEND_EXPOSE_PORT` with the configured port in your `.env` file).

### Running Without Docker

If you prefer to run the backend directly, start the server and worker separately:

```bash
poetry run langboard run
poetry run langboard broker
```

---

## 🔧 Agent Customization with Langflow

Langboard seamlessly integrates with the [Langflow](https://github.com/langflow-ai/langflow) project, allowing you to directly customize and fine-tune your AI agents. Langflow is a visual tool that empowers you to design, configure, and optimize your AI workflows, making it easy to tailor agent behaviors to your specific project needs. Check out the Langflow repository for more details and start customizing your agents today!

---

## 📌 Usage Guidelines

### For Individual & Non-Profit Users

-   **Free Usage:** Clone, use, modify, and redistribute Langboard for personal, educational, research, or non-profit projects.
-   **Community Driven:** Contributions and feedback from the community are highly appreciated to enhance and evolve the project.

### For Commercial Users

-   **Mandatory Sponsorship:**
    -   Commercial use requires regular sponsorship via [GitHub Sponsors](https://github.com/sponsors/yamonco) or a separate commercial licensing agreement.
    -   **Before Deployment:** Ensure you have met the sponsorship requirements or consulted with the YAMON management team.
-   **Refer to License:** Detailed commercial usage terms are outlined in the LICENSE file.

---

## 🤝 Contributing

We welcome contributions from developers and project enthusiasts! Here’s how you can get involved:

1. **Fork the Repository:** Create your own copy to work on new features or fixes.
2. **Create a Branch:** Develop your changes in a dedicated branch.
3. **Submit a Pull Request:** Send your changes for review and integration.
4. **Join the Discussion:** Engage with us on GitHub Issues and Discussions to share ideas and improvements.

---

## 📄 License

This project is licensed under the [Elastic License 2.0 (ELv2)](LICENSE).

-   **Individual & Non-Profit Users:** Free to use, modify, and redistribute under the terms of the Elastic License 2.0.
-   **Commercial Users:** Must adhere to the restrictions of the Elastic License 2.0. Commercial use is only permitted in compliance with the License, which may require obtaining a separate commercial license.

For full details, please see the LICENSE file.

---

## 📬 Official Contact

-   **Email:** battlecruser@yamon.io
-   **GitHub Issues:** [Langboard Issues](https://github.com/yamonco/langboard/issues)

---

## 🔗 Additional Information

-   **Official Website:** Stay updated with the latest news and documentation at [our website](https://langboard.yamon.io).
-   **Community Resources:** Explore our community forums, blogs, and tutorials to get the most out of Langboard.
