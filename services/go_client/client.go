package main

import (
	"bytes"
	"context"
	"fmt"
	"strings"
	"time"
	"log"

	"github.com/RoundRobinHood/cogniflight-cloud/backend/client"
	"github.com/goccy/go-yaml"
)

func GetPilotFromServer(ctx context.Context, api_client client.SocketClient, username string) (*PilotInfo, error) {
	stdout := &bytes.Buffer{}
	stderr := &bytes.Buffer{}
	status, err := api_client.RunCommand(ctx, client.CommandOptions{
		Command: fmt.Sprintf("cat /home/%s/user.profile", username),
		Stdin:   strings.NewReader(""),
		Stdout:  stdout,
		Stderr:  stderr,
	})
	if err != nil {
		return nil, fmt.Errorf("failed to get pilot's user profile: %v", err)
	}

	if status != 0 {
		return nil, fmt.Errorf("cat command for pilot data failed: %s", stderr.String())
	}

	json_bytes, err := yaml.YAMLToJSON(stdout.Bytes())
	if err != nil {
		return nil, fmt.Errorf("failed to convert user profile to JSON: %v", err)
	}

	stdout.Reset()
	stderr.Reset()
	status, err = api_client.RunCommand(ctx, client.CommandOptions{
		Command: "mkdir -p flights && ls -yl flights",
		Stdin:   strings.NewReader(""),
		Stdout:  stdout,
		Stderr:  stderr,
	})
	if err != nil {
		return nil, fmt.Errorf("failed to check flights: %v", err)
	}

	if status != 0 {
		return nil, fmt.Errorf("command failed while trying to get flight files: %v", err)
	}

	var files []FileInfo
	output := stdout.String()
	if len(output) == 0 {
		files = []FileInfo{}
	} else {
		if err := yaml.UnmarshalContext(ctx, []byte(output), &files); err != nil {
			return nil, fmt.Errorf("ls returned invalid yaml: %v", err)
		}
	}

	latest_file := -1
	max_num := 0
	for i, file := range files {
		flight_id, ok := strings.CutSuffix(file.Name, ".flight")
		if !ok {
			continue
		}
		var num int
		if _, err := fmt.Sscan(flight_id, &num); err != nil {
			continue
		}
		if num > max_num {
			latest_file = i
			max_num = num
		}
	}

	flight_id := ""
	if latest_file == -1 {
		log.Println("No flight files, craeting one...")
		stdout.Reset()
		stderr.Reset()
		timestamp := time.Now().UnixNano()
		status, err := api_client.RunCommand(ctx, client.CommandOptions{
			Command: fmt.Sprintf("tee flights/%d.flight", timestamp),
			Stdin:   strings.NewReader(""),
			Stdout:  stdout,
			Stderr:  stderr,
		})
		if err != nil {
			return nil, fmt.Errorf("failed to create flight (%d): %v", timestamp, err)
		}

		if status != 0 {
			return nil, fmt.Errorf("tee command failed for flight %d: %v", timestamp, err)
		}
	} else {
		log.Println("Found a flight file: ", max_num)
		stdout.Reset()
		stderr.Reset()
		status, err := api_client.RunCommand(ctx, client.CommandOptions{
			Command: fmt.Sprintf("cat flights/%d.flight", max_num),
			Stdin:   strings.NewReader(""),
			Stdout:  stdout,
			Stderr:  stderr,
		})
		if err != nil {
			return nil, fmt.Errorf("failed to check flight (%d): %v", max_num, err)
		}

		if status != 0 {
			return nil, fmt.Errorf("cat command failed for flight %d: %v", max_num, err)
		}

		var file FlightFile
		if err := yaml.UnmarshalContext(ctx, stdout.Bytes(), &file); err != nil {
			return nil, fmt.Errorf("invalid flight YAML: %v", err)
		}

		if file.EndTimestamp == nil {
			log.Println("Flight file relevant, no end yet")
			flight_id = fmt.Sprint(max_num)
		} else {
			log.Println("Flight file is finalized, creating a new one...")
			flight_id = fmt.Sprint(time.Now().UnixNano())
			stdout.Reset()
			stderr.Reset()
			status, err := api_client.RunCommand(ctx, client.CommandOptions{
				Command: fmt.Sprintf("tee flights/%s.flight", flight_id),
				Stdin:   strings.NewReader(""),
				Stdout:  stdout,
				Stderr:  stderr,
			})
			if err != nil {
				return nil, fmt.Errorf("failed to make flight file: %v", err)
			}

			if status != 0 {
				return nil, fmt.Errorf("tee command failed to create flight file: %v", err)
			}
		}
	}

	return &PilotInfo{
		Username:      username,
		FlightID:      flight_id,
		Authenticated: "true",
		PersonalData:  string(json_bytes),
	}, nil
}
