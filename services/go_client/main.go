package main

import (
	"context"
	"fmt"
	"log"
	"os"
	"strings"
	"time"

	"github.com/RoundRobinHood/cogniflight-cloud/backend/client"
	_ "github.com/joho/godotenv/autoload"
	"github.com/redis/go-redis/v9"
)

func main() {
	redis_host := "localhost"
	if host := os.Getenv("REDIS_HOST"); host != "" {
		redis_host = host
	}
	redis_port := 6379
	if port := os.Getenv("REDIS_PORT"); port != "" {
		if _, err := fmt.Sscan(port, &redis_port); err != nil {
			log.Println("invalid REDIS_PORT: ", err)
			os.Exit(1)
		}
	}
	redis_password := os.Getenv("REDIS_PASSWORD")
	redis_db := 0
	if db := os.Getenv("REDIS_DB"); db != "" {
		if _, err := fmt.Sscan(db, &redis_db); err != nil {
			log.Println("invalid REDIS_DB: ", err)
			os.Exit(1)
		}
	}

	api_username := os.Getenv("API_USERNAME")
	api_password := os.Getenv("API_PASSWORD")
	api_url := os.Getenv("API_URL")
	if api_username == "" {
		log.Println("API_USERNAME missing")
		os.Exit(1)
	}
	if api_password == "" {
		log.Println("API_PASSWORD missing")
		os.Exit(1)
	}
	if api_url == "" {
		log.Println("API_URL missing")
		os.Exit(1)
	}

	log.Println("Initializing redis client...")
	rdb := redis.NewClient(&redis.Options{
		Addr:     fmt.Sprintf("%s:%d", redis_host, redis_port),
		Password: redis_password,
		DB:       redis_db,
	})

	go SyncThread(rdb, APIConfig{api_username, api_password, api_url}, 5*time.Minute)
	sub := rdb.PSubscribe(context.Background(), "__keyspace@0__:cognicore:data:pilot_id_request")

	log.Println("Awaiting incoming messages...")
	for msg := range sub.Channel() {
		if msg.Payload == "hset" {
			val := rdb.HGetAll(context.Background(), "cognicore:data:pilot_id_request")
			if err := val.Err(); err != nil {
				log.Println("failed to get id request from redis: ", err)
				continue
			}

			keys := val.Val()
			username, ok := keys["pilot_username"]
			if !ok {
				continue
			}

			confidence, ok := keys["confidence"]
			if ok {
				log.Printf("Received pilot request for %q (confidence: %s)", username, confidence)
			} else {
				log.Printf("Received pilot request for %q (no confidence set)", username)
			}

			sessID, err := client.Login(api_url+"/login", api_username, api_password)
			if err != nil {
				log.Println("failed to log in to API: ", err)
				continue
			}

			socket, err := client.ConnectSocket(strings.Replace(api_url, "http", "ws", 1)+"/cmd-socket", sessID)
			if err != nil {
				log.Println("failed to open socket connection: ", err)
				continue
			}

			session := client.NewSocketSession(socket)
			api_client, err := session.ConnectClient("https-client")
			if err != nil {
				log.Println("failed to create client on socket: ", err)
				socket.Close()
				continue
			}

			if pilot, err := GetPilotFromServer(context.Background(), api_client, username); err != nil {
				log.Printf("failed to get pilot from server: %v", err)
				rdb.HSet(context.Background(), fmt.Sprintf("cognicore:data:pilot:%s", username), "authenticated", true)
			} else {
				pilot.Authenticated = "true"
				rdb.HSet(context.Background(), fmt.Sprintf("cognicore:data:pilot:%s", username), pilot)
			}
		}
	}
}
