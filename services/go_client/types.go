package main

import (
	"time"

	"github.com/RoundRobinHood/cogniflight-cloud/backend/types"
)

type PilotInfo struct {
	Username      string    `redis:"pilot_username,omitempty"`
	FlightID      string    `redis:"flight_id,omitempty"`
	Authenticated string    `redis:"authenticated,omitempty"`
	PersonalData  string    `redis:"personal_data,omitempty"`
	Embedding     []float64 `redis:"-"`
}

type FileInfo struct {
	Name         string                   `yaml:"name"`
	FileCount    int                      `yaml:"file_count"`
	FileSize     int                      `yaml:"file_size"`
	ModifiedTime string                   `yaml:"modified_time"`
	Permissions  types.FsEntryPermissions `yaml:"permissions"`
	Type         string                   `yaml:"type"`
}

type FlightFile struct {
	EndTimestamp *time.Time `yaml:"end_timestamp"`
}
