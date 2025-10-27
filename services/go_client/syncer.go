package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"strings"
	"time"

	"github.com/RoundRobinHood/cogniflight-cloud/backend/client"
	"github.com/mitchellh/hashstructure/v2"
	"github.com/redis/go-redis/v9"
)

type APIConfig struct {
	Username, Password, URL string
}

func SyncThread(rdb *redis.Client, api_cfg APIConfig, period time.Duration) {
	sync_start:
	sessID, err := client.Login(api_cfg.URL+"/login", api_cfg.Username, api_cfg.Password)
	if err != nil {
		if !strings.Contains(err.Error(), "401") {
			log.Println("failed to connect to server: ", err)
			goto sync_start
		} else {
			log.Fatal("invalid API credentials")
		}
	}

	socket, err := client.ConnectSocket(strings.Replace(api_cfg.URL, "http", "ws", 1)+"/cmd-socket", sessID)
	if err != nil {
		log.Fatal("failed to connect socket: ", err)
	}

	pilot_hashes := map[string]uint64{}
	session := client.NewSocketSession(socket)
	api_client, err := session.ConnectClient("https-client")

	if err != nil {
		log.Fatal("failed to create client on socket: ", err)
	}

	if pilots, err := GetPilots(context.Background(), api_client); err != nil {
		log.Fatal(err)
	} else {
		for _, pilot := range pilots {
			if hash, err := hashstructure.Hash(pilot, hashstructure.FormatV2, &hashstructure.HashOptions{}); err != nil {
				log.Fatal(err)
			} else {
				pilot_hashes[pilot.Username] = hash
			}
	 	}

		// Check now to delete non-existent pilots
		deletes := make([]string, 0)
		if redis_pilots, err := rdb.Keys(context.Background(), "cognicore:data:pilot:*").Result(); err != nil {
			log.Fatal(err)
		} else {
			for _, pilot := range redis_pilots {
				if _, ok := pilot_hashes[strings.TrimPrefix(pilot, "cognicore:data:pilot:")]; !ok {
					deletes = append(deletes, pilot)
				}
			}

		}

		if redis_embeddings, err := rdb.Keys(context.Background(), "cognicore:data:embedding:*").Result(); err != nil {
			log.Fatal(err)
		} else {
			for _, pilot := range redis_embeddings {
				if _, ok := pilot_hashes[strings.TrimPrefix(pilot, "cognicore:data:embedding:")]; !ok {
					deletes = append(deletes, pilot)
				}
			}
		}

		if len(deletes) != 0 {
			if err := rdb.Del(context.Background(), deletes...).Err(); err != nil {
				panic(err)
			}
		}

		// Now sync all pilot info toward Redis
		for _, pilot := range pilots {
			rdb.HSet(context.Background(), fmt.Sprintf("cognicore:data:pilot:%s", pilot.Username), pilot)

			if pilot.Embedding != nil {
				data, err := json.Marshal(pilot.Embedding)
				if err != nil {
					log.Fatal(err)
				}

				rdb.Set(context.Background(), fmt.Sprintf("cognicore:data:embedding:%s", pilot.Username), string(data), 0)
			}
		}
	}

	ticker := time.NewTicker(period)
	for range ticker.C {
		log.Println("Syncing pilots...")

		log.Println("Getting all pilots...")

		pilots, err := GetPilots(context.Background(), api_client)
		if err != nil {
			log.Println("failed to get pilots: ", err)
			continue
		}

		log.Println("Hashing pilots from server...")
		new_hashes := map[string]uint64{}
		new_pilots := map[string]PilotInfo{}

		failed_hash := false
		for _, pilot := range pilots {
			new_pilots[pilot.Username] = pilot
			if hash, err := hashstructure.Hash(pilot, hashstructure.FormatV2, &hashstructure.HashOptions{}); err != nil {
				log.Println("failed to hash pilot: ", err)
				failed_hash = true
				break
			} else {
				new_hashes[pilot.Username] = hash
			}
		}
		if failed_hash {
			continue
		}

		log.Println("All pilots hashed")

		log.Println("Checking for deleted pilots...")
		for pilot_name := range pilot_hashes {
			if _, ok := new_hashes[pilot_name]; !ok {
				log.Println("Pilot deleted: ", pilot_name)
				log.Println("Removing pilot from redis...")

				rdb.Del(context.Background(), fmt.Sprintf("cognicore:data:pilot:%s", pilot_name), fmt.Sprintf("cognicore:data:embedding:%s", pilot_name))
			}
		}

		log.Println("Checking for changed/new pilot hashes...")
		for pilot_name, new_hash := range new_hashes {
			if old_hash := pilot_hashes[pilot_name]; new_hash != old_hash {
				log.Printf("Hash for %q changed from %v to %v, updating redis data...", pilot_name, old_hash, new_hash)

				rdb.HSet(context.Background(), fmt.Sprintf("cognicore:data:pilot:%s", pilot_name), new_pilots[pilot_name])

				if new_pilots[pilot_name].Embedding != nil {
					data, err := json.Marshal(new_pilots[pilot_name].Embedding)
					if err != nil {
						log.Println("failed to marshal new embedding: ", err)
					} else {
						rdb.Set(context.Background(), fmt.Sprintf("cognicore:data:embedding:%s", pilot_name), string(data), 0)
					}
				}
			}
		}
	}
}
