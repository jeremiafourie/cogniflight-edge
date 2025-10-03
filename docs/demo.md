# CogniFlight Complete System Architecture

## 1. Complete System Architecture - Network Schematic & UML Diagram

```mermaid
graph TB
    %% External Layer - Users and Aircraft
    subgraph "External Access Layer"
        PILOT[👤 Pilots<br/>Web Browser]
        ATC[👮 Air Traffic Controllers<br/>Web Browser]
        ADMIN[👨‍💼 System Administrators<br/>Web Browser]
        AIRCRAFT[✈️ Aircraft<br/>Edge Devices]
    end

    %% Edge Computing Layer - Raspberry Pi in Aircraft
    subgraph "Edge Computing Layer - Aircraft Embedded System"
        subgraph "Raspberry Pi 4B Hardware"
            direction TB
            
            subgraph "Input Sensors"
                CAM[📷 Camera<br/>rpicam-vid<br/>640x360 @ 30fps]
                DHT[🌡️ DHT22 Sensor<br/>GPIO Pin 6<br/>Temp & Humidity]
                BLE[💗 BLE HR Sensor<br/>Heart Rate Monitor<br/>HRV Analysis]
                MQ3[🍺 MQ3 Sensor<br/>GPIO Pin 18<br/>Alcohol Detection]
            end
            
            subgraph "CogniCore Redis Hub"
                REDIS[(Redis 7.0<br/>Central Data Store<br/>Pub/Sub Events<br/>Keyspace Notifications)]
            end
            
            subgraph "Microservices Architecture"
                AUTH_SVC[🔐 Authenticator<br/>InsightFace<br/>Pilot Recognition]
                VISION_SVC[👁️ Vision Processor<br/>MediaPipe<br/>EAR/MAR Analysis]
                BIO_SVC[💓 Bio Monitor<br/>BLE + MQ3<br/>HR & Alcohol]
                ENV_SVC[🌡️ Env Monitor<br/>DHT22 Reader<br/>2s Intervals]
                PREDICT_SVC[🧠 Predictor<br/>Data Fusion<br/>Fatigue Analysis]
                ALERT_SVC[🚨 Alert Manager<br/>GPIO Control<br/>RGB LED/Buzzer]
                NET_SVC[📡 Network Connector<br/>MQTT Client<br/>Telemetry]
                HTTPS_SVC[🔒 HTTPS Client<br/>Profile Fetcher<br/>API Client]
            end
            
            subgraph "Output Hardware"
                RGB[💡 RGB LED<br/>Visual Alerts]
                BUZZ[🔔 Buzzer<br/>Audio Alerts]
                VIB[📳 Vibrator<br/>Haptic Feedback]
            end
        end
        
        %% Internal connections in Edge
        CAM --> AUTH_SVC
        CAM --> VISION_SVC
        DHT --> ENV_SVC
        BLE --> BIO_SVC
        MQ3 --> BIO_SVC
        
        AUTH_SVC --> REDIS
        VISION_SVC --> REDIS
        BIO_SVC --> REDIS
        ENV_SVC --> REDIS
        PREDICT_SVC --> REDIS
        HTTPS_SVC --> REDIS
        
        REDIS --> PREDICT_SVC
        REDIS --> ALERT_SVC
        REDIS --> NET_SVC
        
        ALERT_SVC --> RGB
        ALERT_SVC --> BUZZ
        ALERT_SVC --> VIB
    end
    
    %% Network Layer
    subgraph "Network Infrastructure"
        MQTT_BROKER[Mosquitto 2.0<br/>MQTT Broker<br/>Port 8883 TLS]
        TRAEFIK[Traefik<br/>Reverse Proxy<br/>Load Balancer<br/>TLS Termination]
    end
    
    %% Cloud Infrastructure Layer
    subgraph "Cloud Platform - Docker Compose Stack"
        subgraph "Data Pipeline"
            TELEGRAF[Telegraf 1.34<br/>MQTT Consumer<br/>Data Processor]
            INFLUX[(InfluxDB 2.7<br/>Time-Series DB<br/>Telemetry Storage)]
        end
        
        subgraph "Backend Services"
            GO_API[Go Backend<br/>REST API<br/>WebSocket<br/>Port 8080]
            ML_ENGINE[Python ML Engine<br/>Unix Socket Server<br/>Fatigue Models<br/>Analysis Algorithms]
            
            GO_API -.->|Unix Socket<br/>JSON-RPC| ML_ENGINE
        end
        
        subgraph "Data Persistence"
            MONGO[(MongoDB 8.0<br/>Collections:<br/>• users<br/>• flights<br/>• alerts<br/>• edge_nodes<br/>• api_keys<br/>• sessions)]
            GRIDFS[(GridFS<br/>File Storage<br/>User Images<br/>Documents)]
        end
        
        subgraph "Frontend Application"
            REACT[React Dashboard<br/>Vite Dev Server<br/>Desktop UI<br/>Port 5173]
        end
    end
    
    %% External Connections
    AIRCRAFT -->|MQTTS<br/>Port 8883| MQTT_BROKER
    AIRCRAFT -->|HTTPS<br/>API Key Auth| TRAEFIK
    
    PILOT -->|HTTPS| TRAEFIK
    ATC -->|HTTPS| TRAEFIK
    ADMIN -->|HTTPS| TRAEFIK
    
    %% Cloud Internal Connections
    TRAEFIK -->|/api/*| GO_API
    TRAEFIK -->|Static Files| REACT
    
    NET_SVC -->|MQTT Publish| MQTT_BROKER
    HTTPS_SVC -->|REST API| TRAEFIK
    
    MQTT_BROKER --> TELEGRAF
    TELEGRAF -->|Write| INFLUX
    
    GO_API -->|CRUD| MONGO
    GO_API -->|Files| GRIDFS
    GO_API -->|Query| INFLUX
    
    ML_ENGINE -->|Read| INFLUX
    ML_ENGINE -->|Write| MONGO
    
    %% Styling
    classDef edge fill:#fff3e0,stroke:#ff9800,stroke-width:3px
    classDef cloud fill:#e1f5fe,stroke:#0288d1,stroke-width:3px
    classDef data fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px
    classDef network fill:#fce4ec,stroke:#c2185b,stroke-width:2px
    classDef frontend fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    
    class AIRCRAFT,CAM,DHT,BLE,MQ3,AUTH_SVC,VISION_SVC,BIO_SVC,ENV_SVC,PREDICT_SVC,ALERT_SVC,NET_SVC,HTTPS_SVC,RGB,BUZZ,VIB,REDIS edge
    class GO_API,ML_ENGINE,TELEGRAF cloud
    class MONGO,INFLUX,GRIDFS data
    class MQTT_BROKER,TRAEFIK network
    class REACT,PILOT,ATC,ADMIN frontend
```

## 2. Technology Stack Diagram - Hardware & Software Components

```mermaid
graph TB
    subgraph "Hardware Layer"
        subgraph "Edge Hardware - Aircraft"
            RPI[Raspberry Pi 4B<br/>4GB RAM<br/>ARM Cortex-A72]
            
            subgraph "Input Hardware"
                CAMERA[Pi Camera Module<br/>640x360 @ 30fps]
                DHT22[DHT22 Sensor<br/>Temperature & Humidity]
                HR_SENSOR[Polar H10<br/>BLE Heart Rate]
                MQ3_SENSOR[MQ3 Sensor<br/>Alcohol Detection]
            end
            
            subgraph "Output Hardware"
                LED[WS2812B RGB LED<br/>GPIO Pin 10]
                BUZZER[Piezo Buzzer<br/>GPIO Pin 17]
                VIBRATOR[Vibration Motor<br/>GPIO Pin 27]
            end
            
            subgraph "Connectivity"
                WIFI[WiFi Module<br/>802.11ac]
                BT[Bluetooth 5.0<br/>BLE Support]
            end
        end
        
        subgraph "Cloud Hardware"
            SERVER[Cloud Server<br/>Linux Ubuntu<br/>Docker Host]
            STORAGE[Persistent Storage<br/>SSD Volumes]
            NETWORK_HW[Network Infrastructure<br/>Load Balancers<br/>Firewalls]
        end
    end
    
    subgraph "Software Stack"
        subgraph "Edge Software Stack"
            subgraph "Operating System"
                RASPBIAN[Raspberry Pi OS<br/>Debian-based<br/>Linux 6.1]
            end
            
            subgraph "System Services"
                SYSTEMD[systemd<br/>Service Manager<br/>Watchdog Monitor]
                JOURNALD[journald<br/>Logging System]
            end
            
            subgraph "Runtime & Languages"
                PYTHON_EDGE[Python 3.11+<br/>Edge Services]
                REDIS_EDGE[Redis 7.0<br/>Data Hub]
            end
            
            subgraph "Edge Libraries"
                MEDIAPIPE[MediaPipe<br/>Face Detection]
                INSIGHTFACE[InsightFace<br/>Face Recognition]
                OPENCV[OpenCV 4.5<br/>Image Processing]
                BLEAK[Bleak<br/>BLE Library]
                GPIOZERO[gpiozero<br/>GPIO Control]
                PAHO[Paho MQTT<br/>MQTT Client]
            end
        end
        
        subgraph "Cloud Software Stack"
            subgraph "Container Platform"
                DOCKER[Docker 24.0<br/>Container Engine]
                COMPOSE[Docker Compose<br/>Orchestration]
            end
            
            subgraph "Backend Technologies"
                GOLANG[Go 1.24.2<br/>API Server]
                PYTHON_CLOUD[Python 3.12.3<br/>ML Engine]
                NODE[Node.js 18<br/>Frontend Build]
            end
            
            subgraph "Frameworks & Libraries"
                subgraph "Backend Frameworks"
                    GIN[Gin Web Framework<br/>HTTP Router]
                    GORILLA[Gorilla WebSocket<br/>Real-time Comm]
                    MONGO_DRIVER[MongoDB Driver<br/>Database Client]
                end
                
                subgraph "Frontend Frameworks"
                    REACT_FW[React 19.1<br/>UI Framework]
                    VITE[Vite 6.0<br/>Build Tool]
                    TAILWIND[Tailwind CSS<br/>Styling]
                    RECHARTS[Recharts<br/>Data Visualization]
                end
                
                subgraph "ML Libraries"
                    NUMPY[NumPy<br/>Numerical Computing]
                    SCIPY[SciPy<br/>Scientific Computing]
                    SKLEARN[scikit-learn<br/>ML Algorithms]
                    PANDAS[Pandas<br/>Data Analysis]
                end
            end
            
            subgraph "Data Services"
                MONGODB[MongoDB 8.0<br/>Document Store]
                INFLUXDB[InfluxDB 2.7<br/>Time-Series DB]
                GRIDFS_SW[GridFS<br/>File Storage]
                REDIS_CLOUD[Redis Cache<br/>Session Store]
            end
            
            subgraph "Messaging & Networking"
                MOSQUITTO[Mosquitto 2.0<br/>MQTT Broker]
                TELEGRAF_SW[Telegraf 1.34<br/>Data Collection]
                TRAEFIK_SW[Traefik 3.0<br/>Reverse Proxy]
            end
            
            subgraph "Security"
                TLS[TLS 1.3<br/>Encryption]
                BCRYPT[bcrypt<br/>Password Hashing]
                JWT[JWT<br/>Token Auth]
                RBAC[RBAC<br/>Role-Based Access]
            end
        end
    end
    
    subgraph "Communication Protocols"
        subgraph "Edge Protocols"
            I2C[I2C Protocol<br/>Sensor Communication]
            SPI[SPI Protocol<br/>High-Speed Data]
            UART[UART<br/>Serial Communication]
            PWM[PWM<br/>LED Control]
        end
        
        subgraph "Network Protocols"
            MQTTS[MQTT over TLS<br/>Telemetry Protocol]
            HTTPS[HTTPS<br/>REST API]
            WSS[WebSocket Secure<br/>Real-time Updates]
            GRPC[Unix Socket<br/>IPC Communication]
        end
        
        subgraph "Data Formats"
            JSON[JSON<br/>API Payloads]
            BSON[BSON<br/>MongoDB Format]
            MSGPACK[MessagePack<br/>Binary Serialization]
            PROTOBUF[Protocol Buffers<br/>Telemetry Data]
        end
    end
    
    %% Connections showing technology relationships
    RPI --> RASPBIAN
    RASPBIAN --> SYSTEMD
    SYSTEMD --> PYTHON_EDGE
    PYTHON_EDGE --> MEDIAPIPE
    PYTHON_EDGE --> INSIGHTFACE
    PYTHON_EDGE --> OPENCV
    PYTHON_EDGE --> BLEAK
    PYTHON_EDGE --> GPIOZERO
    PYTHON_EDGE --> PAHO
    PYTHON_EDGE --> REDIS_EDGE
    
    SERVER --> DOCKER
    DOCKER --> COMPOSE
    COMPOSE --> GOLANG
    COMPOSE --> PYTHON_CLOUD
    COMPOSE --> NODE
    
    GOLANG --> GIN
    GOLANG --> GORILLA
    GOLANG --> MONGO_DRIVER
    
    NODE --> REACT_FW
    NODE --> VITE
    REACT_FW --> TAILWIND
    REACT_FW --> RECHARTS
    
    PYTHON_CLOUD --> NUMPY
    PYTHON_CLOUD --> SCIPY
    PYTHON_CLOUD --> SKLEARN
    PYTHON_CLOUD --> PANDAS
    
    %% Protocol connections
    CAMERA --> I2C
    DHT22 --> UART
    LED --> PWM
    HR_SENSOR --> BT
    
    PAHO --> MQTTS
    GIN --> HTTPS
    GORILLA --> WSS
    
    %% Styling
    classDef hardware fill:#ffebee,stroke:#c62828,stroke-width:3px
    classDef software fill:#e3f2fd,stroke:#1565c0,stroke-width:2px
    classDef protocol fill:#f3e5f5,stroke:#6a1b9a,stroke-width:2px
    classDef framework fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px
    
    class RPI,CAMERA,DHT22,HR_SENSOR,MQ3_SENSOR,LED,BUZZER,VIBRATOR,SERVER,STORAGE,NETWORK_HW hardware
    class RASPBIAN,SYSTEMD,DOCKER,COMPOSE,GOLANG,PYTHON_EDGE,PYTHON_CLOUD,NODE software
    class I2C,SPI,UART,PWM,MQTTS,HTTPS,WSS,GRPC protocol
    class MEDIAPIPE,INSIGHTFACE,GIN,REACT_FW,NUMPY framework
```

## 3. Data Flow and System State Diagram

```mermaid
stateDiagram-v2
    [*] --> SYSTEM_INIT: Power On
    
    SYSTEM_INIT --> SCANNING: Services Started
    
    SCANNING --> INTRUDER_DETECTED: Unknown Face
    SCANNING --> PILOT_IDENTIFIED: Known Pilot
    SCANNING --> SYSTEM_ERROR: Service Failure
    
    INTRUDER_DETECTED --> SCANNING: Face Lost
    INTRUDER_DETECTED --> SYSTEM_ERROR: Critical Error
    
    PILOT_IDENTIFIED --> MONITORING_ACTIVE: Profile Loaded
    PILOT_IDENTIFIED --> SCANNING: Profile Error
    
    MONITORING_ACTIVE --> ALERT_MILD: Fatigue Score 0.3-0.6
    MONITORING_ACTIVE --> ALERT_MODERATE: Fatigue Score 0.6-0.8
    MONITORING_ACTIVE --> ALERT_SEVERE: Fatigue Score >0.8
    MONITORING_ACTIVE --> SCANNING: Pilot Left
    
    ALERT_MILD --> MONITORING_ACTIVE: Fatigue Reduced
    ALERT_MILD --> ALERT_MODERATE: Fatigue Increased
    
    ALERT_MODERATE --> ALERT_MILD: Fatigue Reduced
    ALERT_MODERATE --> ALERT_SEVERE: Fatigue Increased
    
    ALERT_SEVERE --> ALERT_MODERATE: Fatigue Reduced
    ALERT_SEVERE --> SYSTEM_ERROR: Critical Condition
    
    SYSTEM_ERROR --> SYSTEM_CRASHED: Watchdog Failed
    SYSTEM_ERROR --> SCANNING: Recovery Success
    
    SYSTEM_CRASHED --> [*]: System Shutdown
    
    note right of MONITORING_ACTIVE
        Continuous Data Collection:
        - Vision: 30fps
        - HR: Real-time BLE
        - Environment: 2s intervals
        - Fusion: 20Hz processing
    end note
    
    note left of ALERT_SEVERE
        Multi-Modal Alerts:
        - RED RGB LED
        - Loud Buzzer
        - Strong Vibration
        - Cloud Notification
    end note
```

## 4. Service Communication Architecture

```mermaid
graph LR
    subgraph "Event-Driven Architecture"
        subgraph "Publishers"
            VP[Vision<br/>Processor]
            BM[Bio<br/>Monitor]
            EM[Env<br/>Monitor]
            AU[Authenticator]
        end
        
        subgraph "Redis Core"
            KS[Keyspace<br/>Notifications]
            PS[Pub/Sub<br/>Channels]
            HS[Hash<br/>Storage]
        end
        
        subgraph "Subscribers"
            PR[Predictor]
            AM[Alert<br/>Manager]
            NC[Network<br/>Connector]
            HC[HTTPS<br/>Client]
        end
        
        VP -->|vision_data| HS
        BM -->|hr_sensor| HS
        BM -->|alcohol_detected| HS
        EM -->|env_data| HS
        AU -->|pilot:id| HS
        
        HS -->|keyspace:vision| KS
        HS -->|keyspace:hr| KS
        HS -->|keyspace:env| KS
        
        KS -->|instant| PR
        KS -->|instant| NC
        
        PR -->|system_state| PS
        PS -->|state_change| AM
        
        AU -->|pilot_request| HC
        HC -->|pilot_profile| HS
    end
    
    subgraph "Data Fusion Algorithm"
        EAR[EAR Score<br/>50% weight]
        CLOSURE[Eye Closure<br/>30% weight]
        MICRO[Microsleeps<br/>15% weight]
        BLINK[Blink Rate<br/>5% weight]
        HR[Heart Rate<br/>25% optional]
        
        EAR --> FUSION[Fusion<br/>Calculator]
        CLOSURE --> FUSION
        MICRO --> FUSION
        BLINK --> FUSION
        HR -.->|if available| FUSION
        
        FUSION --> SCORE[Fatigue<br/>Score<br/>0.0 - 1.0]
        
        SCORE --> STAGE{Classification}
        STAGE -->|< 0.3| ACTIVE[Active]
        STAGE -->|0.3-0.6| MILD[Mild]
        STAGE -->|0.6-0.8| MODERATE[Moderate]
        STAGE -->|> 0.8| SEVERE[Severe]
    end
```

## System Characteristics Summary

### Edge System (Raspberry Pi)
- **Processing**: Real-time, event-driven microservices
- **Communication**: Redis-based pub/sub with keyspace notifications
- **Sensors**: Multi-modal (vision, biometric, environmental)
- **Alerts**: Hardware-based immediate feedback
- **Resilience**: Systemd watchdog, automatic recovery
- **Offline**: Fully functional without network

### Cloud Platform
- **Architecture**: Containerized microservices (Docker Compose)
- **Backend**: Go REST API with WebSocket support
- **Frontend**: React desktop-style web application
- **Data**: MongoDB (operational) + InfluxDB (time-series)
- **ML**: Python engine with Unix socket IPC
- **Security**: TLS, JWT, RBAC, API key authentication

### Network & Communication
- **Telemetry**: MQTT over TLS (throttled to prevent spam)
- **API**: RESTful HTTPS with Traefik routing
- **Real-time**: WebSocket for dashboard updates
- **IPC**: Unix sockets for ML engine communication

This architecture ensures:
1. **Aviation Safety**: Real-time fatigue detection with <1s response
2. **Reliability**: Redundant monitoring, automatic recovery
3. **Scalability**: Microservices can scale independently
4. **Security**: Multi-layer authentication and encryption
5. **Performance**: Optimized for edge computing constraints
