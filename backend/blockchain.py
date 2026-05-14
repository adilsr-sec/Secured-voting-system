import hashlib
import json
from time import time
from typing import List, Dict

class Block:
    def __init__(self, index: int, transactions: List[Dict], timestamp: float, previous_hash: str):
        self.index = index
        self.transactions = transactions
        self.timestamp = timestamp
        self.previous_hash = previous_hash
        self.nonce = 0
        self.hash = self.calculate_hash()

    def calculate_hash(self) -> str:
        """Calculate the hash of the block."""
        block_string = json.dumps({
            "index": self.index,
            "transactions": self.transactions,
            "timestamp": self.timestamp,
            "previous_hash": self.previous_hash,
            "nonce": self.nonce
        }, sort_keys=True).encode()
        
        return hashlib.sha256(block_string).hexdigest()

    def mine_block(self, difficulty: int):
        """Mine the block with proof of work."""
        while self.hash[:difficulty] != "0" * difficulty:
            self.nonce += 1
            self.hash = self.calculate_hash()

class Blockchain:
    def __init__(self):
        self.chain: List[Block] = []
        self.difficulty = 2  # Number of leading zeros required in hash
        self.pending_transactions: List[Dict] = []
        self.mining_reward = 0  # No mining reward for voting system
        
        # Create genesis block
        self.create_genesis_block()

    def create_genesis_block(self):
        """Create the first block in the chain."""
        genesis_block = Block(0, [], time(), "0")
        genesis_block.mine_block(self.difficulty)
        self.chain.append(genesis_block)

    def get_latest_block(self) -> Block:
        """Get the most recent block in the chain."""
        return self.chain[-1]

    def add_voter_record(self, voter_data: Dict):
        """Add a new voter registration record to pending transactions."""
        transaction = {
            "type": "voter_registration",
            "timestamp": time(),
            "data": {
                "voter_id": voter_data["voter_id"],
                "name": voter_data["name"],
                "age": voter_data["age"],
                "district": voter_data["district"],
                "state": voter_data["state"],
                # Hash of sensitive data (for privacy)
                "data_hash": hashlib.sha256(
                    json.dumps(voter_data, sort_keys=True).encode()
                ).hexdigest()
            }
        }
        self.pending_transactions.append(transaction)

    def add_vote_record(self, voter_id: str, vote_hash: str):
        """Add a new voting record to pending transactions."""
        transaction = {
            "type": "vote_cast",
            "timestamp": time(),
            "data": {
                "voter_id": voter_id,
                "vote_hash": vote_hash  # Encrypted vote data
            }
        }
        self.pending_transactions.append(transaction)

    def mine_pending_transactions(self):
        """Create a new block with pending transactions and add it to the chain."""
        if not self.pending_transactions:
            return False

        new_block = Block(
            len(self.chain),
            self.pending_transactions,
            time(),
            self.get_latest_block().hash
        )

        new_block.mine_block(self.difficulty)
        self.chain.append(new_block)
        self.pending_transactions = []
        return True

    def is_chain_valid(self) -> bool:
        """Verify the integrity of the blockchain."""
        for i in range(1, len(self.chain)):
            current_block = self.chain[i]
            previous_block = self.chain[i-1]

            # Verify current block's hash
            if current_block.hash != current_block.calculate_hash():
                return False

            # Verify chain linkage
            if current_block.previous_hash != previous_block.hash:
                return False

        return True

    def get_voter_history(self, voter_id: str) -> List[Dict]:
        """Get all transactions related to a specific voter."""
        voter_transactions = []
        for block in self.chain:
            for transaction in block.transactions:
                if (transaction["type"] == "voter_registration" and 
                    transaction["data"]["voter_id"] == voter_id):
                    voter_transactions.append(transaction)
                elif (transaction["type"] == "vote_cast" and 
                      transaction["data"]["voter_id"] == voter_id):
                    voter_transactions.append(transaction)
        return voter_transactions

    def get_all_votes(self) -> List[Dict]:
        """Get all voting transactions."""
        votes = []
        for block in self.chain:
            for transaction in block.transactions:
                if transaction["type"] == "vote_cast":
                    votes.append(transaction)
        return votes

    def export_chain(self) -> str:
        """Export the blockchain data as JSON string."""
        chain_data = []
        for block in self.chain:
            chain_data.append({
                "index": block.index,
                "timestamp": block.timestamp,
                "transactions": block.transactions,
                "previous_hash": block.previous_hash,
                "hash": block.hash,
                "nonce": block.nonce
            })
        return json.dumps(chain_data, indent=2) 