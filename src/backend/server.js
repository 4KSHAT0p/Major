import express, { raw } from "express";
import cors from "cors";
const server = express();

server.use(express.json());
server.use(cors());

//in memory store  (can use redis in prod)
const ehr_mapping = {};

server.get("/:patient_id", (req, res) => {
  const patient_id = req.params.patient_id;
  if (patient_id in ehr_mapping)
    return res.status(200).json(ehr_mapping[patient_id]);
  else res.sendStatus(404);
});

server.post("/:patient_id", (req, res) => {
  const patient_id = req.params.patient_id;
  if (patient_id in ehr_mapping) return res.sendStatus(403);
  else {
    const ehr_id = req.body.ehr_id;
    ehr_mapping[patient_id] = ehr_id;
    return res.sendStatus(201);
  }
});

server.listen(3000, () => {
  console.log("server listening");
});
