# Architettura dell'Applicazione

```mermaid
graph TD
    A[Main Process] -->|IPC| B[Renderer Process]
    A --> C[Rclone CLI]
    B --> D[React Components]
    D --> E[TransferManager]
    D --> F[ConfigManager]
    A --> G[Store]
